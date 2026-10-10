"""Administrador de estado de los collectors."""

from enum import Enum
from typing import Dict


class SourceState(str, Enum):
    """Estado de salud de una fuente de recolección."""

    OK = "ok"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class SourceHealthManager:
    """Rastrea el estado de las diferentes fuentes de datos."""

    def __init__(self) -> None:
        self._states: Dict[str, SourceState] = {}
        self._reasons: Dict[str, str] = {}

    def set_state(self, source: str, state: SourceState, reason: str = "") -> None:
        """Actualiza el estado de una fuente.

        Args:
            source: Nombre de la fuente (e.g., 'psi', 'energy').
            state: El nuevo estado de la fuente.
            reason: Mensaje opcional explicando el estado (e.g., el error ocurrido).
        """
        self._states[source] = state
        if reason:
            self._reasons[source] = reason
        elif source in self._reasons and state == SourceState.OK:
            del self._reasons[source]

    def get_state(self, source: str) -> SourceState:
        """Obtiene el estado actual de una fuente.

        Args:
            source: Nombre de la fuente.

        Returns:
            El estado de la fuente, por defecto OK si no se ha reportado nada.
        """
        return self._states.get(source, SourceState.OK)

    def get_reason(self, source: str) -> str:
        """Obtiene el motivo del estado actual, si lo hay."""
        return self._reasons.get(source, "")
