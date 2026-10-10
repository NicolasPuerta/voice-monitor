"""Cliente y constructores para interactuar con Gemini de forma segura."""

import time
import logging
from enum import Enum
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, DeadlineExceeded, RetryError

from app.core.config import Settings
from app.core.privacy import PrivacySanitizer
from app.domain.context import SystemContext
from app.domain.events import Event
from app.domain.gemini import GeminiContext, SafeEventSummary

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

        return GeminiContext(
            system_load_avg=resources.load_average or (0.0, 0.0, 0.0),
            memory_percent=resources.memory_percent,
            battery_percent=resources.battery_percent,
            battery_plugged=resources.battery_plugged,
            primary_event=primary,
            recent_events=[],  # Por ahora vaco; MR7 coalesce lograra integrarlos si se pidiera, o se rellenara con db.
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


class GeminiClient:
    """Cliente oficial de Gemini. Aislado de collectors y de psutil."""

    def __init__(self, settings: Settings, circuit_breaker: CircuitBreaker | None = None):
        self.settings = settings
        self.enabled = settings.app.gemini_enabled
        self.model_name = settings.app.gemini_model

        # Nunca se loguea la API key.
        if self.enabled and settings.app.gemini_api_key:
            genai.configure(api_key=settings.app.gemini_api_key.get_secret_value())
            self.model = genai.GenerativeModel(self.model_name)
        else:
            self.model = None

        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.max_retries = 2

    def generate(self, prompt: str, system_instruction: str | None = None) -> str | None:
        """Enva un prompt a Gemini y retorna el texto generado."""
        if not self.enabled or not self.model:
            logger.debug("Gemini deshabilitado. No se realiza llamada externa.")
            return None

        if not self.circuit_breaker.can_execute():
            logger.warning("Llamada denegada por el Circuit Breaker.")
            return None

        # Si el modelo no soporta system_instruction nativo en init, lo pre-pendemos.
        full_prompt = prompt
        if system_instruction:
            full_prompt = f"{system_instruction}\n\n=== DATOS ===\n{prompt}"

        for attempt in range(self.max_retries + 1):
            try:
                response = self.model.generate_content(full_prompt)
                self.circuit_breaker.record_success()
                return response.text
            except ResourceExhausted:
                # Rate limit (429)
                logger.warning("Gemini Rate Limit Excedido.")
                self.circuit_breaker.record_failure()
                time.sleep(2**attempt)  # Backoff exponencial dbil
            except (DeadlineExceeded, RetryError) as e:
                logger.error(f"Error de red/Timeout llamando a Gemini: {e}")
                self.circuit_breaker.record_failure()
            except Exception as e:
                logger.error(f"Error inesperado de Gemini: {e}")
                self.circuit_breaker.record_failure()
                break  # Errores no transitorios no se reintentan

        return None
