"""Pruebas de los modelos de snapshots."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.snapshots import (
    PressureStall,
    ProcessSnapshot,
    ResourceSnapshot,
    SystemPressure,
    SystemSnapshot,
)

DOMAIN_DIR = Path(__file__).resolve().parents[2] / "app" / "domain"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_resources(**overrides: object) -> ResourceSnapshot:
    """Construye un ResourceSnapshot válido con valores sobrescribibles."""
    values: dict[str, object] = {
        "cpu_percent": 12.5,
        "cpu_count_logical": 8,
        "memory_total_bytes": 16_000,
        "memory_used_bytes": 8_000,
        "memory_available_bytes": 8_000,
        "memory_percent": 50.0,
    }
    values.update(overrides)
    return ResourceSnapshot(**values)


def test_process_snapshot_defaults() -> None:
    """Verifica los valores por defecto de un proceso."""
    process = ProcessSnapshot(pid=1, name="systemd")
    assert process.cpu_percent == 0.0
    assert process.memory_rss_bytes is None
    assert process.memory_percent is None
    assert process.executable is None
    assert process.cmdline is None
    assert process.cgroup is None
    assert process.username is None
    assert process.started_at is None


def test_process_cpu_may_exceed_100_but_memory_may_not() -> None:
    """Verifica que la CPU de un proceso pueda superar 100 y la memoria no."""
    assert ProcessSnapshot(pid=1, name="x", cpu_percent=250.0).cpu_percent == 250.0
    with pytest.raises(ValidationError):
        ProcessSnapshot(pid=1, name="x", memory_percent=101.0)


def test_process_rejects_negative_pid() -> None:
    """Verifica que un PID negativo sea inválido."""
    with pytest.raises(ValidationError):
        ProcessSnapshot(pid=-1, name="x")


def test_resource_snapshot_optional_fields_default_to_none() -> None:
    """Verifica que los datos opcionales (batería, red, PSI) sean None."""
    resources = make_resources()
    assert resources.battery_percent is None
    assert resources.battery_plugged is None
    assert resources.load_average is None
    assert resources.disk_read_bytes_per_s is None
    assert resources.swap_total_bytes == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"cpu_percent": 100.1},
        {"memory_percent": -0.1},
        {"cpu_count_logical": 0},
        {"memory_total_bytes": -1},
        {"battery_percent": 101},
        {"net_recv_bytes_per_s": -5.0},
    ],
)
def test_resource_snapshot_rejects_out_of_range(overrides: dict[str, object]) -> None:
    """Verifica que los valores fuera de rango sean inválidos."""
    with pytest.raises(ValidationError):
        make_resources(**overrides)


def test_pressure_models() -> None:
    """Verifica que la presión del sistema acepte métricas parciales."""
    pressure = SystemPressure(cpu_some=PressureStall(avg10=1.0, avg60=2.0, avg300=3.0))
    assert pressure.cpu_some is not None
    assert pressure.cpu_some.avg60 == 2.0
    assert pressure.memory_full is None
    with pytest.raises(ValidationError):
        PressureStall(avg10=101, avg60=0, avg300=0)


def test_system_snapshot_composition() -> None:
    """Verifica la composición de un snapshot completo."""
    snapshot = SystemSnapshot(
        collected_at=NOW,
        resources=make_resources(),
        processes=(ProcessSnapshot(pid=1, name="systemd"),),
        uptime_s=120.0,
    )
    assert snapshot.pressure is None
    assert snapshot.processes[0].name == "systemd"
    assert SystemSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


def test_system_snapshot_requires_timezone_aware_datetime() -> None:
    """Verifica que la fecha de recolección deba tener zona horaria."""
    with pytest.raises(ValidationError):
        SystemSnapshot(collected_at=datetime(2026, 1, 1), resources=make_resources())


def test_models_are_immutable_and_reject_unknown_fields() -> None:
    """Verifica que los modelos sean inmutables y estrictos con los campos."""
    process = ProcessSnapshot(pid=1, name="x")
    with pytest.raises(ValidationError):
        process.name = "y"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ProcessSnapshot(pid=1, name="x", unknown=1)  # type: ignore[call-arg]


def test_domain_does_not_depend_on_psutil() -> None:
    """Verifica que el dominio no importe psutil."""
    for source_file in DOMAIN_DIR.rglob("*.py"):
        assert "psutil" not in source_file.read_text(encoding="utf-8"), source_file
