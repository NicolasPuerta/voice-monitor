"""Pruebas de las enumeraciones del dominio."""

import pytest

from app.domain.enums import ConfidenceLevel, EventDecision, EventSeverity, EventType


@pytest.mark.parametrize(
    "enum_class", [EventType, EventSeverity, EventDecision, ConfidenceLevel]
)
def test_enum_values_are_unique_lowercase_strings(enum_class: type[str]) -> None:
    """Verifica que los valores sean cadenas únicas en minúsculas."""
    values = [member.value for member in enum_class]  # type: ignore[attr-defined]
    assert len(values) == len(set(values))
    assert all(value == value.lower() for value in values)


def test_enums_can_be_built_from_value() -> None:
    """Verifica que los enums se construyan desde su valor textual."""
    assert EventType("cpu_spike") is EventType.CPU_SPIKE
    assert EventSeverity("critical") is EventSeverity.CRITICAL
    assert EventDecision("spoken") is EventDecision.SPOKEN
    assert ConfidenceLevel("high") is ConfidenceLevel.HIGH


def test_enums_are_string_compatible() -> None:
    """Verifica que los enums sean cadenas y se serialicen como su valor."""
    assert isinstance(EventSeverity.INFO, str)
    assert str(EventSeverity.INFO.value) == "info"


def test_invalid_enum_value_raises_error() -> None:
    """Verifica que un valor desconocido lance ValueError."""
    with pytest.raises(ValueError):
        EventType("unknown")
