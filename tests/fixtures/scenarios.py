"""Fixtures reutilizables de escenarios para pruebas."""

from datetime import datetime, timezone
import pytest

from app.core.fixtures import (
    ReplayTick,
    create_cpu_spike_scenario,
    create_docker_scenario,
    create_electron_saturation_scenario,
    create_firefox_scenario,
    create_idle_scenario,
    create_memory_pressure_scenario,
    create_process_failures_scenario,
)

BASE_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def idle_ticks() -> list[ReplayTick]:
    return create_idle_scenario(BASE_TIME, ticks=5)


@pytest.fixture
def cpu_spike_ticks() -> list[ReplayTick]:
    return create_cpu_spike_scenario(BASE_TIME, ticks=5)


@pytest.fixture
def memory_pressure_ticks() -> list[ReplayTick]:
    return create_memory_pressure_scenario(BASE_TIME, ticks=5)


@pytest.fixture
def firefox_ticks() -> list[ReplayTick]:
    return create_firefox_scenario(BASE_TIME, children_count=10, ticks=5)


@pytest.fixture
def docker_ticks() -> list[ReplayTick]:
    return create_docker_scenario(BASE_TIME, ticks=5)


@pytest.fixture
def process_failures_ticks() -> list[ReplayTick]:
    return create_process_failures_scenario(BASE_TIME, ticks=4)


@pytest.fixture
def electron_saturation_ticks() -> list[ReplayTick]:
    return create_electron_saturation_scenario(BASE_TIME, num_processes=50, ticks=6)
