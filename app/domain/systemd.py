"""Modelos de dominio para el subsistema systemd."""

from enum import Enum

from pydantic import AwareDatetime

from app.domain.base import DomainModel


class ServiceState(str, Enum):
    """Estado de activación de una unidad de systemd."""

    ACTIVE = "active"
    RELOADING = "reloading"
    INACTIVE = "inactive"
    FAILED = "failed"
    ACTIVATING = "activating"
    DEACTIVATING = "deactivating"
    UNKNOWN = "unknown"


class UnitSnapshot(DomainModel):
    """Instantánea de una unidad de systemd."""

    name: str
    description: str = ""
    load_state: str = "loaded"
    active_state: ServiceState = ServiceState.UNKNOWN
    sub_state: str = ""
    unit_type: str = "service"

    @property
    def is_failed(self) -> bool:
        """Indica si la unidad se encuentra en estado de fallo."""
        return (
            self.active_state == ServiceState.FAILED
            or self.sub_state == "failed"
        )


class SystemdSnapshot(DomainModel):
    """Instantánea global del estado de systemd."""

    collected_at: AwareDatetime
    units_total: int = 0
    units_active: int = 0
    units_failed: int = 0
    failed_units: tuple[UnitSnapshot, ...] = ()
    services: tuple[UnitSnapshot, ...] = ()
