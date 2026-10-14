"""Administrador de estado y degradación elegante de los collectors y fuentes."""

import logging
import time
from enum import Enum
from typing import Dict

logger = logging.getLogger(__name__)


class SourceState(str, Enum):
    """Estado de salud de una fuente de recolección."""

    OK = "ok"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class SourceHealthManager:
    """Rastrea la salud de las fuentes con circuit breaker, backoff y logs sin spam."""

    def __init__(
        self,
        base_backoff_s: float = 2.0,
        max_backoff_s: float = 60.0,
        log_quiet_interval_s: float = 60.0,
    ) -> None:
        self.base_backoff_s = base_backoff_s
        self.max_backoff_s = max_backoff_s
        self.log_quiet_interval_s = log_quiet_interval_s

        self._states: Dict[str, SourceState] = {}
        self._reasons: Dict[str, str] = {}
        self._consecutive_failures: Dict[str, int] = {}
        self._last_failure_time: Dict[str, float] = {}
        self._last_success_time: Dict[str, float] = {}
        self._current_backoff: Dict[str, float] = {}
        self._last_logged_time: Dict[str, float] = {}
        self._last_logged_state: Dict[str, SourceState] = {}

    def set_state(self, source: str, state: SourceState, reason: str = "") -> None:
        """Actualiza el estado de una fuente directamente."""
        old_state = self.get_state(source)
        self._states[source] = state
        if reason:
            self._reasons[source] = reason
        elif source in self._reasons and state == SourceState.OK:
            del self._reasons[source]

        self._log_transition_if_needed(source, old_state, state, reason, time.time())

    def record_success(self, source: str, now: float | None = None) -> None:
        """Registra una operación exitosa de la fuente, recuperando su estado."""
        current_time = time.time() if now is None else now
        old_state = self.get_state(source)

        self._consecutive_failures[source] = 0
        self._current_backoff[source] = self.base_backoff_s
        self._last_success_time[source] = current_time
        self._states[source] = SourceState.OK
        if source in self._reasons:
            del self._reasons[source]

        if old_state != SourceState.OK:
            self._log_transition_if_needed(
                source, old_state, SourceState.OK, "Fuente recuperada", current_time
            )

    def record_failure(
        self,
        source: str,
        reason: str = "",
        now: float | None = None,
        threshold_degraded: int = 2,
        threshold_disabled: int = 5,
    ) -> None:
        """Registra un fallo en la fuente.

        Aplica backoff exponencial y circuit breaker según los umbrales configurados.
        """
        current_time = time.time() if now is None else now
        failures = self._consecutive_failures.get(source, 0) + 1
        self._consecutive_failures[source] = failures
        self._last_failure_time[source] = current_time
        self._reasons[source] = reason

        # Backoff exponencial con límite superior
        prev_backoff = self._current_backoff.get(source, self.base_backoff_s)
        self._current_backoff[source] = min(self.max_backoff_s, prev_backoff * 2)

        old_state = self.get_state(source)
        if failures >= threshold_disabled:
            new_state = SourceState.DISABLED
        elif failures >= threshold_degraded:
            new_state = SourceState.DEGRADED
        else:
            new_state = old_state

        self._states[source] = new_state
        self._log_transition_if_needed(
            source, old_state, new_state, reason, current_time
        )

    def can_attempt(self, source: str, now: float | None = None) -> bool:
        """Determina si se debe intentar usar una fuente según su ventana de backoff."""
        state = self.get_state(source)
        if state == SourceState.OK:
            return True

        current_time = time.time() if now is None else now
        last_failure = self._last_failure_time.get(source, 0.0)
        backoff = self._current_backoff.get(source, self.base_backoff_s)

        # Si ha pasado la ventana de enfriamiento, se permite una prueba de recuperación
        return (current_time - last_failure) >= backoff

    def is_healthy(self, source: str) -> bool:
        """Indica si una fuente se encuentra en estado completamente OK."""
        return self.get_state(source) == SourceState.OK

    def is_source_failed(self, source: str) -> bool:
        """Indica si una fuente ha fallado o se encuentra degradada."""
        return not self.is_healthy(source)

    def get_state(self, source: str) -> SourceState:
        """Obtiene el estado actual de una fuente."""
        return self._states.get(source, SourceState.OK)

    def get_reason(self, source: str) -> str:
        """Obtiene el motivo del estado actual, si lo hay."""
        return self._reasons.get(source, "")

    def get_consecutive_failures(self, source: str) -> int:
        """Retorna el número de fallos consecutivos observados en la fuente."""
        return self._consecutive_failures.get(source, 0)

    def get_all_states(self) -> Dict[str, SourceState]:
        """Retorna una copia del estado de todas las fuentes registradas."""
        return dict(self._states)

    def _log_transition_if_needed(
        self,
        source: str,
        old_state: SourceState,
        new_state: SourceState,
        reason: str,
        current_time: float,
    ) -> None:
        """Registra mensajes de log evitando saturación (sin spam)."""
        last_log = self._last_logged_time.get(source, 0.0)
        last_state = self._last_logged_state.get(source)

        # Loguear si hubo un cambio de estado o si ha pasado el intervalo de quietud
        state_changed = old_state != new_state or last_state != new_state
        time_elapsed = (current_time - last_log) >= self.log_quiet_interval_s

        if state_changed or (time_elapsed and new_state != SourceState.OK):
            self._last_logged_time[source] = current_time
            self._last_logged_state[source] = new_state

            msg = f"Fuente '{source}' cambió a estado {new_state.value}."
            if reason:
                msg += f" Motivo: {reason}"

            if new_state == SourceState.DISABLED:
                logger.error(msg)
            elif new_state == SourceState.DEGRADED:
                logger.warning(msg)
            else:
                logger.info(msg)
