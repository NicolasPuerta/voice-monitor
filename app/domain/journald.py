"""Modelos de dominio para los registros estructurados de journald."""

from enum import Enum
from typing import Any

from pydantic import AwareDatetime

from app.domain.base import DomainModel


class JournaldEventType(str, Enum):
    """Tipo de evento extraído de las bitácoras de journald."""

    OOM_KILL = "oom_kill"
    SERVICE_FAILURE = "service_failure"
    SYSTEM_ERROR = "system_error"
    WARNING = "warning"
    INFO = "info"


class JournalEntry(DomainModel):
    """Entrada individual estructurada de journald."""

    timestamp: AwareDatetime
    message: str
    priority: int = 6
    cursor: str | None = None
    unit: str | None = None
    identifier: str | None = None
    event_type: JournaldEventType = JournaldEventType.INFO
    raw_fields: dict[str, Any] = {}


class JournaldSnapshot(DomainModel):
    """Instantánea de eventos incrementales recolectados de journald."""

    collected_at: AwareDatetime
    cursor: str | None = None
    total_new_entries: int = 0
    oom_events: tuple[JournalEntry, ...] = ()
    service_failures: tuple[JournalEntry, ...] = ()
    error_events: tuple[JournalEntry, ...] = ()
