"""Modelos de eventos detectados en el sistema."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field

from app.domain.base import DomainModel, NonNegativeFloat, NonNegativeInt
from app.domain.enums import (
    ConfidenceLevel,
    EventDecision,
    EventSeverity,
    EventType,
)


def _utc_now() -> datetime:
    """Obtiene la fecha y hora actual en UTC.

    Returns:
        Fecha y hora actual con zona horaria UTC.
    """
    return datetime.now(timezone.utc)


class EventMetadata(DomainModel):
    """Datos de contexto que acompañan a un evento."""

    process_pid: NonNegativeInt | None = None
    """Proceso involucrado, si aplica."""

    process_name: str | None = None
    """Nombre del proceso involucrado, si aplica."""

    metric_name: str | None = None
    """Nombre de la métrica que originó el evento."""

    metric_value: float | None = None
    """Valor observado de la métrica."""

    threshold: float | None = None
    """Umbral que se superó, si aplica."""

    unit: str | None = None
    """Unidad de la métrica (por ejemplo, ``%`` o ``bytes``)."""

    duration_s: NonNegativeFloat | None = None
    """Segundos que lleva activa la condición."""

    extra: dict[str, str] = Field(default_factory=dict)
    """Datos adicionales en formato clave-valor."""


class Event(DomainModel):
    """Evento detectado, con su gravedad y decisión de priorización."""

    id: UUID = Field(default_factory=uuid4)
    """Identificador único del evento."""

    event_type: EventType
    """Tipo de evento."""

    severity: EventSeverity
    """Gravedad del evento."""

    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    """Confianza en que el evento es real y relevante."""

    decision: EventDecision | None = None
    """Decisión de priorización; ``None`` mientras no se haya evaluado."""

    detected_at: AwareDatetime = Field(default_factory=_utc_now)
    """Momento de la detección (con zona horaria)."""

    summary: str = Field(min_length=1)
    """Descripción breve del evento, legible por una persona."""

    metadata: EventMetadata = Field(default_factory=EventMetadata)
    """Datos de contexto del evento."""
