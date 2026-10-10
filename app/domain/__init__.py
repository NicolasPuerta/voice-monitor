"""Modelos de dominio independientes de cualquier librería de recolección."""

from app.domain.enums import (
    ConfidenceLevel,
    EventDecision,
    EventPriority,
    EventSeverity,
    EventType,
)
from app.domain.events import Event, EventMetadata, ScoreBreakdown, ScoreResult
from app.domain.snapshots import (
    PressureStall,
    ProcessSnapshot,
    ResourceSnapshot,
    SystemPressure,
    SystemSnapshot,
)
from app.domain.context import ApplicationGroup, SystemContext
from app.domain.knowledge import KnowledgeSource, ProcessKnowledge

__all__ = [
    "ApplicationGroup",
    "ConfidenceLevel",
    "Event",
    "EventDecision",
    "EventMetadata",
    "EventPriority",
    "EventSeverity",
    "EventType",
    "KnowledgeSource",
    "PressureStall",
    "ProcessKnowledge",
    "ProcessSnapshot",
    "ResourceSnapshot",
    "ScoreBreakdown",
    "ScoreResult",
    "SystemContext",
    "SystemPressure",
    "SystemSnapshot",
]
