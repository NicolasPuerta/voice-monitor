"""Cliente y constructores para interactuar con Gemini de forma segura."""

import time
import logging
from enum import Enum
from typing import Any
import httpx
from google import genai
from google.genai import errors, types

from app.core.config import Settings
from app.core.privacy import PrivacySanitizer
from app.domain.context import SystemContext
from app.domain.events import Event
from app.domain.gemini import GeminiContext, SafeEventSummary
from app.domain.snapshots import PressureStall

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Implementa un circuit breaker para proteger contra fallos continuos de red/API."""

    def __init__(self, failure_threshold: int = 3, recovery_timeout_s: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.last_failure_time: float | None = None

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning("Circuit breaker OPEN. Llamadas a Gemini suspendidas.")

    def record_success(self) -> None:
        self.failures = 0
        self.state = CircuitState.CLOSED

    def can_execute(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if (
                self.last_failure_time
                and (time.time() - self.last_failure_time) > self.recovery_timeout_s
            ):
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        # HALF_OPEN (probando una llamada)
        return True


class GeminiContextBuilder:
    """Extrae un contexto seguro y reducido desde el SystemContext y un Evento."""

    def __init__(self, sanitizer: PrivacySanitizer):
        self.sanitizer = sanitizer

    def build(
        self, event: Event, sys_ctx: SystemContext, process_knowledge: str | None = None
    ) -> GeminiContext:
        """Construye el GeminiContext sanitizando la informacin sensible."""

        primary = self._build_safe_summary(event)

        # Obtener los recursos bsicos y sanitizar
        resources = sys_ctx.resources
        pressure = sys_ctx.pressure

        def _avg10(stall: PressureStall | None) -> float | None:
            return stall.avg10 if stall is not None else None

        return GeminiContext(
            system_load_avg=resources.load_average or (0.0, 0.0, 0.0),
            memory_percent=resources.memory_percent,
            cpu_percent=resources.cpu_percent,
            cpu_count_logical=resources.cpu_count_logical,
            cpu_pressure_avg10=_avg10(pressure.cpu_some) if pressure else None,
            memory_pressure_avg10=_avg10(pressure.memory_some) if pressure else None,
            io_pressure_avg10=_avg10(pressure.io_some) if pressure else None,
            battery_percent=resources.battery_percent,
            battery_plugged=resources.battery_plugged,
            primary_event=primary,
            recent_events=[],  # Eventos recientes si aplica
            process_knowledge=self.sanitizer.sanitize_text(process_knowledge),
        )

    def _build_safe_summary(self, event: Event) -> SafeEventSummary:
        return SafeEventSummary(
            event_type=event.event_type.value,
            severity=event.severity.value,
            priority=(
                event.score_result.priority.value if event.score_result else "ambient"
            ),
            score=event.score_result.score if event.score_result else 0.0,
            reasons=event.score_result.reasons if event.score_result else [],
            app_key=self.sanitizer.sanitize_text(event.metadata.app_key or "unknown")
            or "unknown",
            app_name=self.sanitizer.sanitize_text(event.metadata.app_name or "unknown")
            or "unknown",
            summary=self.sanitizer.sanitize_text(event.summary) or "",
            duration_s=event.metadata.duration_s,
        )


# Códigos HTTP transitorios que vale la pena reintentar
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class GeminiClient:
    """Cliente oficial de Gemini (SDK ``google-genai``). Aislado de collectors."""

    def __init__(
        self,
        settings: Settings,
        circuit_breaker: CircuitBreaker | None = None,
        timeout_s: float = 30.0,
    ):
        self.settings = settings
        self.enabled = settings.gemini.enabled
        self.model_name = settings.gemini.model

        self.client: Any | None = None
        # Nunca se loguea la API key.
        if self.enabled and settings.gemini.api_key:
            self.client = genai.Client(
                api_key=settings.gemini.api_key.get_secret_value(),
                http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
            )

        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.max_retries = 2

    def _build_config(
        self, system_instruction: str | None
    ) -> types.GenerateContentConfig:
        """Configura JSON nativo y, en Gemini 2.5 Flash, desactiva el razonamiento."""
        thinking = None
        # El razonamiento añade segundos de latencia a una narración que debe ser
        # inmediata. Solo la familia 2.5 Flash acepta thinking_budget=0; varios
        # modelos posteriores (p. ej. *-flash-lite) lo rechazan con 400.
        if self.model_name.startswith("gemini-2.5-flash"):
            thinking = types.ThinkingConfig(thinking_budget=0)
        return types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            temperature=0.3,
            thinking_config=thinking,
        )

    def generate(self, prompt: str, system_instruction: str | None = None) -> str | None:
        """Envía un prompt a Gemini y retorna el texto generado."""
        if not self.enabled or not self.client:
            logger.debug("Gemini deshabilitado. No se realiza llamada externa.")
            return None

        if not self.circuit_breaker.can_execute():
            logger.warning("Llamada denegada por el Circuit Breaker.")
            return None

        config = self._build_config(system_instruction)
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name, contents=prompt, config=config
                )
                self.circuit_breaker.record_success()
                text = getattr(response, "text", None)
                return str(text) if text else None
            except errors.APIError as e:
                self.circuit_breaker.record_failure()
                if e.code not in RETRYABLE_STATUS:
                    # 400/401/403/404: clave, modelo o petición inválidos
                    logger.error("Gemini rechazó la petición (%s): %s", e.code, e.message)
                    break
                if e.code == 429:
                    logger.warning("Gemini Rate Limit Excedido.")
                else:
                    logger.warning("Gemini no disponible temporalmente (%s).", e.code)
            except httpx.TransportError as e:
                # Timeouts y errores de conexión
                logger.error("Error de red/Timeout llamando a Gemini: %s", e)
                self.circuit_breaker.record_failure()
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Error inesperado de Gemini: %s", e)
                self.circuit_breaker.record_failure()
                break  # Errores no transitorios no se reintentan

            if attempt < self.max_retries and self.circuit_breaker.can_execute():
                time.sleep(2**attempt)  # Backoff exponencial
            else:
                break

        return None
