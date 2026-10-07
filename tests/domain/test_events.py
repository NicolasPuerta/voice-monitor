"""Pruebas de los modelos de eventos."""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.enums import (
    ConfidenceLevel,
    EventDecision,
    EventSeverity,
    EventType,
)
from app.domain.events import Event, EventMetadata


def make_event(**overrides: object) -> Event:
    """Construye un Event válido con valores sobrescribibles."""
    values: dict[str, object] = {
        "event_type": EventType.CPU_SPIKE,
        "severity": EventSeverity.HIGH,
        "summary": "Pico de CPU detectado",
    }
    values.update(overrides)
    return Event(**values)


def test_event_defaults() -> None:
    """Verifica los valores por defecto de un evento."""
    event = make_event()
    assert isinstance(event.id, UUID)
    assert event.confidence is ConfidenceLevel.MEDIUM
    assert event.decision is None
    assert event.detected_at.tzinfo is not None
    assert event.metadata == EventMetadata()


def test_event_ids_are_unique() -> None:
    """Verifica que cada evento tenga un identificador distinto."""
    assert make_event().id != make_event().id


def test_event_requires_non_empty_summary() -> None:
    """Verifica que el resumen no pueda estar vacío."""
    with pytest.raises(ValidationError):
        make_event(summary="")


def test_event_requires_timezone_aware_detection_time() -> None:
    """Verifica que la fecha de detección deba tener zona horaria."""
    with pytest.raises(ValidationError):
        make_event(detected_at=datetime(2026, 1, 1))


def test_event_rejects_invalid_enum_values() -> None:
    """Verifica que los valores de enum inválidos sean rechazados."""
    with pytest.raises(ValidationError):
        make_event(severity="catastrophic")


def test_event_json_roundtrip() -> None:
    """Verifica que un evento sobreviva a la serialización JSON."""
    event = make_event(
        decision=EventDecision.NARRATE,
        detected_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        metadata=EventMetadata(
            process_pid=42,
            process_name="firefox",
            metric_name="cpu_percent",
            metric_value=97.5,
            threshold=80.0,
            unit="%",
            duration_s=12.0,
            extra={"core": "3"},
        ),
    )
    assert Event.model_validate_json(event.model_dump_json()) == event


def test_event_metadata_defaults_and_validation() -> None:
    """Verifica los valores por defecto y las restricciones de la metadata."""
    metadata = EventMetadata()
    assert metadata.process_pid is None
    assert metadata.extra == {}
    with pytest.raises(ValidationError):
        EventMetadata(duration_s=-1.0)
    with pytest.raises(ValidationError):
        EventMetadata(process_pid=-1)


def test_event_is_immutable() -> None:
    """Verifica que un evento no pueda modificarse tras crearse."""
    event = make_event()
    with pytest.raises(ValidationError):
        event.severity = EventSeverity.LOW  # type: ignore[misc]
