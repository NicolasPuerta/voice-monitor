"""Modelos de dominio independientes de cualquier librería de recolección."""

from app.domain.enums import (
    ConfidenceLevel,
    EventDecision,
    EventSeverity,
    EventType,
)
from app.domain.events import Event, EventMetadata
from app.domain.snapshots import (
    PressureStall,
    ProcessSnapshot,
    ResourceSnapshot,
    SystemPressure,
    SystemSnapshot,
)

__all__ = [
    "ConfidenceLevel",
    "Event",
    "EventDecision",
    "EventMetadata",
    "EventSeverity",
    "EventType",
    "PressureStall",
    "ProcessSnapshot",
    "ResourceSnapshot",
    "SystemPressure",
    "SystemSnapshot",
]
