"""Modelos de eventos detectados en el sistema."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field

from app.domain.base import DomainModel, NonNegativeFloat, NonNegativeInt
from app.domain.enums import (
    ConfidenceLevel,
    EventDecision,
    EventPriority,
    EventSeverity,
    EventType,
)


def _utc_now() -> datetime:
    """Obtiene la fecha y hora actual en UTC."""
    return datetime.now(timezone.utc)


class EventMetadata(DomainModel):
    """Datos de contexto que acompañan a un evento."""

    process_pid: NonNegativeInt | None = None
    process_name: str | None = None
    app_key: str | None = None
    app_name: str | None = None
    metric_name: str | None = None
    metric_value: float | None = None
    threshold: float | None = None
    unit: str | None = None
    duration_s: NonNegativeFloat | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class ScoreBreakdown(DomainModel):
    """Desglose del puntaje de un evento para su explicabilidad."""

    impact: float
    novelty: float
    anomaly: float
    risk: float
    relevance: float
    repetition_penalty: float

    @property
    def total(self) -> float:
        return (
            self.impact
            + self.novelty
            + self.anomaly
            + self.risk
            + self.relevance
            - self.repetition_penalty
        )


class ScoreResult(DomainModel):
    """Resultado final de la priorización de un evento."""

    score: float
    priority: EventPriority
    breakdown: ScoreBreakdown
    reasons: list[str] = Field(default_factory=list)


class Event(DomainModel):
    """Evento detectado."""

    id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    severity: EventSeverity
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    
    # Propiedades calculadas en la tubería
    decision: EventDecision | None = None
    score_result: ScoreResult | None = None
    
    detected_at: AwareDatetime = Field(default_factory=_utc_now)
    summary: str = Field(min_length=1)
    metadata: EventMetadata = Field(default_factory=EventMetadata)
