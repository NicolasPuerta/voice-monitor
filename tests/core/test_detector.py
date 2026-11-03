"""Pruebas del RuleBasedDetector."""

from datetime import datetime, timezone

from app.core.detector import RuleBasedDetector
from app.domain.context import ApplicationGroup, SystemContext
from app.domain.enums import EventType
from app.domain.snapshots import ResourceSnapshot

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_context(system_cpu: float, app_cpu: float) -> SystemContext:
    return SystemContext(
        collected_at=NOW,
        resources=ResourceSnapshot(
            cpu_percent=system_cpu,
            cpu_count_logical=8,
            memory_total_bytes=1000,
            memory_used_bytes=500,
            memory_available_bytes=500,
            memory_percent=50.0,
        ),
        apps=(
            ApplicationGroup(
                app_key="exe:/usr/bin/stress",
                name="stress",
                processes=(),
                cpu_percent=app_cpu,
            ),
        ),
    )


def test_app_cpu_uses_its_own_threshold() -> None:
    detector = RuleBasedDetector(cpu_threshold=80.0, app_cpu_threshold=25.0)
    events = detector.detect(make_context(system_cpu=30.0, app_cpu=26.0), NOW)
    assert [e.event_type for e in events] == [EventType.CPU_SPIKE]
    assert events[0].metadata.threshold == 25.0


def test_app_cpu_threshold_defaults_to_system_threshold() -> None:
    detector = RuleBasedDetector(cpu_threshold=80.0)
    assert detector.detect(make_context(system_cpu=30.0, app_cpu=26.0), NOW) == []
