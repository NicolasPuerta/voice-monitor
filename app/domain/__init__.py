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
from app.domain.gemini import AnalysisResult, GeminiContext, SafeEventSummary
from app.domain.prompts import ANALYSIS_SYSTEM_PROMPT_V1
from app.domain.audio import AudioData, AudioFormat

__all__ = [
    "ANALYSIS_SYSTEM_PROMPT_V1",
    "AnalysisResult",
    "ApplicationGroup",
    "AudioData",
    "AudioFormat",
    "ConfidenceLevel",
    "Event",
    "EventDecision",
    "EventMetadata",
    "EventPriority",
    "EventSeverity",
    "EventType",
    "GeminiContext",
    "KnowledgeSource",
    "PressureStall",
    "ProcessKnowledge",
    "ProcessSnapshot",
    "ResourceSnapshot",
    "SafeEventSummary",
    "ScoreBreakdown",
    "ScoreResult",
    "SystemContext",
    "SystemPressure",
    "SystemSnapshot",
]
