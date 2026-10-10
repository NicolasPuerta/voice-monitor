"""Pruebas para los collectors del sistema (recursos, PSI, energa)."""

from pathlib import Path

import pytest
from unittest.mock import patch, MagicMock

from app.collectors.health import SourceHealthManager, SourceState
from app.collectors.system import (
    EnergyStateCollector,
    PSICollector,
    SystemResourceCollector,
)
from app.domain.snapshots import ResourceSnapshot


@pytest.fixture
def health_manager() -> SourceHealthManager:
    return SourceHealthManager()


def test_source_health_manager_defaults() -> None:
    manager = SourceHealthManager()
    assert manager.get_state("any") == SourceState.OK
    assert manager.get_reason("any") == ""


def test_source_health_manager_updates(health_manager: SourceHealthManager) -> None:
    health_manager.set_state("psi", SourceState.DEGRADED, "error test")
    assert health_manager.get_state("psi") == SourceState.DEGRADED
    assert health_manager.get_reason("psi") == "error test"

    health_manager.set_state("psi", SourceState.OK)
    assert health_manager.get_state("psi") == SourceState.OK
    assert health_manager.get_reason("psi") == ""


@patch("app.collectors.system.psutil")
def test_system_resource_collector_ok(
    mock_psutil: MagicMock, health_manager: SourceHealthManager
) -> None:
    mock_psutil.cpu_percent.return_value = 15.5
    mock_psutil.cpu_count.return_value = 4
    mock_psutil.getloadavg.return_value = (0.5, 0.4, 0.3)

    mock_mem = MagicMock()
    mock_mem.total = 16000
    mock_mem.used = 8000
    mock_mem.available = 8000
    mock_mem.percent = 50.0
    mock_psutil.virtual_memory.return_value = mock_mem

    mock_swap = MagicMock()
    mock_swap.total = 4000
    mock_swap.used = 1000
    mock_swap.percent = 25.0
    mock_psutil.swap_memory.return_value = mock_swap

    collector = SystemResourceCollector(health_manager)
    snapshot = collector.collect()

    assert snapshot.cpu_percent == 15.5
    assert snapshot.cpu_count_logical == 4
    assert snapshot.load_average == (0.5, 0.4, 0.3)
    assert snapshot.memory_total_bytes == 16000
    assert snapshot.memory_available_bytes == 8000
    assert snapshot.swap_total_bytes == 4000
    assert snapshot.swap_used_bytes == 1000

    assert health_manager.get_state(collector.name) == SourceState.OK


@patch("app.collectors.system.psutil")
def test_system_resource_collector_fallback_on_error(
    mock_psutil: MagicMock, health_manager: SourceHealthManager
) -> None:
    mock_psutil.cpu_percent.side_effect = Exception("Crash")

    collector = SystemResourceCollector(health_manager)
    snapshot = collector.collect()

    assert snapshot.cpu_percent == 0.0
    assert snapshot.memory_total_bytes == 0
    assert health_manager.get_state(collector.name) == SourceState.DEGRADED


@pytest.fixture
def mock_proc_psi(tmp_path: Path) -> Path:
    proc_dir = tmp_path / "proc"
    psi_dir = proc_dir / "pressure"
    psi_dir.mkdir(parents=True)

    (psi_dir / "cpu").write_text("some avg10=1.5 avg60=2.0 avg300=3.0 total=100\n")
    (psi_dir / "memory").write_text(
        "some avg10=4.0 avg60=5.0 avg300=6.0 total=200\n"
        "full avg10=7.0 avg60=8.0 avg300=9.0 total=300\n"
    )
    (psi_dir / "io").write_text("some avg10=10.0 avg60=11.0 avg300=12.0 total=400\n")
    return proc_dir


def test_psi_collector_with_sources(
    mock_proc_psi: Path, health_manager: SourceHealthManager
) -> None:
    collector = PSICollector(health_manager, proc_root=mock_proc_psi)
    pressure = collector.collect()

    assert pressure.cpu_some is not None
    assert pressure.cpu_some.avg10 == 1.5
    assert pressure.memory_full is not None
    assert pressure.memory_full.avg60 == 8.0
    assert pressure.io_some is not None
    assert pressure.io_some.avg300 == 12.0

    assert health_manager.get_state(collector.name) == SourceState.OK


def test_psi_collector_missing_sources(
    tmp_path: Path, health_manager: SourceHealthManager
) -> None:
    collector = PSICollector(health_manager, proc_root=tmp_path / "proc_empty")
    pressure = collector.collect()

    assert pressure.cpu_some is None
    assert pressure.memory_some is None
    assert pressure.io_some is None
    assert health_manager.get_state(collector.name) == SourceState.DISABLED


@pytest.fixture
def mock_sys_battery(tmp_path: Path) -> Path:
    sys_dir = tmp_path / "sys"
    power_dir = sys_dir / "class" / "power_supply"
    power_dir.mkdir(parents=True)

    bat_dir = power_dir / "BAT0"
    bat_dir.mkdir()
    (bat_dir / "type").write_text("Battery\n")
    (bat_dir / "capacity").write_text("85\n")
    (bat_dir / "status").write_text("Discharging\n")

    ac_dir = power_dir / "AC"
    ac_dir.mkdir()
    (ac_dir / "type").write_text("Mains\n")
    (ac_dir / "online").write_text("0\n")

    return sys_dir


def test_energy_collector_with_battery(
    mock_sys_battery: Path, health_manager: SourceHealthManager
) -> None:
    collector = EnergyStateCollector(health_manager, sys_root=mock_sys_battery)
    battery_percent, battery_plugged = collector.collect()

    assert battery_percent == 85.0
    assert battery_plugged is False
    assert health_manager.get_state(collector.name) == SourceState.OK


def test_energy_collector_missing_sources(
    tmp_path: Path, health_manager: SourceHealthManager
) -> None:
    collector = EnergyStateCollector(health_manager, sys_root=tmp_path / "sys_empty")
    battery_percent, battery_plugged = collector.collect()

    assert battery_percent is None
    assert battery_plugged is None
    assert health_manager.get_state(collector.name) == SourceState.DISABLED
