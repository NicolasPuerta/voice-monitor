"""Generadores de escenarios sintéticos y fixtures para pruebas y benchmarks."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.collectors.health import SourceHealthManager
from app.core.context import SystemContextBuilder
from app.domain.context import SystemContext
from app.domain.events import Event
from app.domain.snapshots import (
    PressureStall,
    ProcessSnapshot,
    ResourceSnapshot,
    SystemPressure,
)


@dataclass
class ReplayTick:
    """Instante del sistema listo para reproducir en el ReplayEngine."""

    timestamp: datetime
    context: SystemContext
    injected_events: list[Event] = field(default_factory=list)


def create_idle_scenario(
    start_time: datetime | None = None, ticks: int = 5, step_s: float = 1.0
) -> list[ReplayTick]:
    """Genera un escenario de sistema inactivo (idle) con bajo consumo."""
    start = start_time or datetime.now(timezone.utc)
    builder = SystemContextBuilder()
    health = SourceHealthManager()
    scenario = []

    for i in range(ticks):
        ts = start + timedelta(seconds=i * step_s)
        resources = ResourceSnapshot(
            cpu_percent=1.5,
            cpu_count_logical=4,
            load_average=(0.1, 0.15, 0.1),
            memory_total_bytes=8 * 1024 * 1024 * 1024,
            memory_used_bytes=2 * 1024 * 1024 * 1024,
            memory_available_bytes=6 * 1024 * 1024 * 1024,
            memory_percent=25.0,
        )
        procs = [
            ProcessSnapshot(pid=1, name="systemd", cpu_percent=0.1),
            ProcessSnapshot(pid=100, name="bash", parent_pid=1, cpu_percent=0.0),
            ProcessSnapshot(
                pid=200, name="voice-monitor", parent_pid=100, cpu_percent=0.8
            ),
        ]
        ctx = builder.build(
            collected_at=ts,
            resources=resources,
            processes=procs,
            health_manager=health,
        )
        scenario.append(ReplayTick(timestamp=ts, context=ctx))

    return scenario


def create_cpu_spike_scenario(
    start_time: datetime | None = None, ticks: int = 5, step_s: float = 1.0
) -> list[ReplayTick]:
    """Genera un escenario con un proceso intensivo que genera un pico de CPU."""
    start = start_time or datetime.now(timezone.utc)
    builder = SystemContextBuilder()
    health = SourceHealthManager()
    scenario = []

    for i in range(ticks):
        ts = start + timedelta(seconds=i * step_s)
        resources = ResourceSnapshot(
            cpu_percent=96.0,
            cpu_count_logical=4,
            load_average=(3.5, 2.0, 1.0),
            memory_total_bytes=8 * 1024 * 1024 * 1024,
            memory_used_bytes=4 * 1024 * 1024 * 1024,
            memory_available_bytes=4 * 1024 * 1024 * 1024,
            memory_percent=50.0,
        )
        procs = [
            ProcessSnapshot(pid=1, name="systemd", cpu_percent=0.1),
            ProcessSnapshot(
                pid=2001,
                name="ffmpeg",
                parent_pid=1,
                executable="/usr/bin/ffmpeg",
                cpu_percent=92.5,
                memory_rss_bytes=500 * 1024 * 1024,
                cgroup="/user.slice/ffmpeg.scope",
            ),
        ]
        ctx = builder.build(
            collected_at=ts,
            resources=resources,
            processes=procs,
            health_manager=health,
        )
        scenario.append(ReplayTick(timestamp=ts, context=ctx))

    return scenario


def create_memory_pressure_scenario(
    start_time: datetime | None = None, ticks: int = 5, step_s: float = 1.0
) -> list[ReplayTick]:
    """Genera un escenario con alta presión de memoria y métricas PSI altas."""
    start = start_time or datetime.now(timezone.utc)
    builder = SystemContextBuilder()
    health = SourceHealthManager()
    scenario = []

    for i in range(ticks):
        ts = start + timedelta(seconds=i * step_s)
        resources = ResourceSnapshot(
            cpu_percent=35.0,
            cpu_count_logical=4,
            memory_total_bytes=8 * 1024 * 1024 * 1024,
            memory_used_bytes=7600 * 1024 * 1024,
            memory_available_bytes=400 * 1024 * 1024,
            memory_percent=95.0,
            swap_total_bytes=2 * 1024 * 1024 * 1024,
            swap_used_bytes=1500 * 1024 * 1024,
            swap_percent=75.0,
        )
        pressure = SystemPressure(
            memory_some=PressureStall(avg10=35.0, avg60=20.0, avg300=10.0),
            memory_full=PressureStall(avg10=18.0, avg60=10.0, avg300=5.0),
        )
        procs = [
            ProcessSnapshot(
                pid=3001,
                name="heavy_dataset_loader",
                parent_pid=1,
                cpu_percent=30.0,
                memory_rss_bytes=6000 * 1024 * 1024,
            ),
        ]
        ctx = builder.build(
            collected_at=ts,
            resources=resources,
            processes=procs,
            pressure=pressure,
            health_manager=health,
        )
        scenario.append(ReplayTick(timestamp=ts, context=ctx))

    return scenario


def create_firefox_scenario(
    start_time: datetime | None = None,
    children_count: int = 10,
    ticks: int = 5,
    step_s: float = 1.0,
) -> list[ReplayTick]:
    """Genera un escenario con Firefox y múltiples procesos hijos agrupados."""
    start = start_time or datetime.now(timezone.utc)
    builder = SystemContextBuilder()
    health = SourceHealthManager()
    scenario = []

    for i in range(ticks):
        ts = start + timedelta(seconds=i * step_s)
        resources = ResourceSnapshot(
            cpu_percent=60.0,
            cpu_count_logical=4,
            memory_total_bytes=16 * 1024 * 1024 * 1024,
            memory_used_bytes=8 * 1024 * 1024 * 1024,
            memory_available_bytes=8 * 1024 * 1024 * 1024,
            memory_percent=50.0,
        )
        cgroup = "/user.slice/app-gnome-firefox-123.scope"
        procs = [
            ProcessSnapshot(
                pid=1000,
                name="firefox",
                parent_pid=1,
                executable="/usr/bin/firefox",
                cgroup=cgroup,
                cpu_percent=12.0,
                memory_rss_bytes=600 * 1024 * 1024,
            )
        ]
        for child_idx in range(1, children_count + 1):
            procs.append(
                ProcessSnapshot(
                    pid=1000 + child_idx,
                    name="Web Content",
                    parent_pid=1000,
                    executable="/usr/bin/firefox",
                    cgroup=cgroup,
                    cpu_percent=4.5,
                    memory_rss_bytes=250 * 1024 * 1024,
                )
            )

        ctx = builder.build(
            collected_at=ts,
            resources=resources,
            processes=procs,
            health_manager=health,
        )
        scenario.append(ReplayTick(timestamp=ts, context=ctx))

    return scenario


def create_docker_scenario(
    start_time: datetime | None = None, ticks: int = 5, step_s: float = 1.0
) -> list[ReplayTick]:
    """Genera un escenario con procesos en contenedores Docker."""
    start = start_time or datetime.now(timezone.utc)
    builder = SystemContextBuilder()
    health = SourceHealthManager()
    scenario = []

    for i in range(ticks):
        ts = start + timedelta(seconds=i * step_s)
        resources = ResourceSnapshot(
            cpu_percent=45.0,
            cpu_count_logical=4,
            memory_total_bytes=16 * 1024 * 1024 * 1024,
            memory_used_bytes=6 * 1024 * 1024 * 1024,
            memory_available_bytes=10 * 1024 * 1024 * 1024,
            memory_percent=37.5,
        )
        cgroup = "/system.slice/docker-container123abc456.scope"
        procs = [
            ProcessSnapshot(
                pid=4000,
                name="node",
                parent_pid=1,
                executable="/usr/local/bin/node",
                cgroup=cgroup,
                cpu_percent=32.0,
                memory_rss_bytes=400 * 1024 * 1024,
            ),
            ProcessSnapshot(
                pid=4001,
                name="redis-server",
                parent_pid=1,
                executable="/usr/bin/redis-server",
                cgroup=cgroup,
                cpu_percent=5.0,
                memory_rss_bytes=150 * 1024 * 1024,
            ),
        ]
        ctx = builder.build(
            collected_at=ts,
            resources=resources,
            processes=procs,
            health_manager=health,
        )
        scenario.append(ReplayTick(timestamp=ts, context=ctx))

    return scenario


def create_process_failures_scenario(
    start_time: datetime | None = None, ticks: int = 4, step_s: float = 1.0
) -> list[ReplayTick]:
    """Genera un escenario donde un proceso desaparece o falla abruptamente."""
    start = start_time or datetime.now(timezone.utc)
    builder = SystemContextBuilder()
    health = SourceHealthManager()
    scenario = []

    for i in range(ticks):
        ts = start + timedelta(seconds=i * step_s)
        resources = ResourceSnapshot(
            cpu_percent=30.0 if i < 2 else 5.0,
            cpu_count_logical=4,
            memory_total_bytes=8 * 1024 * 1024 * 1024,
            memory_used_bytes=3 * 1024 * 1024 * 1024,
            memory_available_bytes=5 * 1024 * 1024 * 1024,
            memory_percent=37.5,
        )
        procs = [ProcessSnapshot(pid=1, name="systemd", cpu_percent=0.1)]
        # El proceso 5001 corre intensamente en los ticks 0 y 1, luego desaparece
        if i < 2:
            procs.append(
                ProcessSnapshot(
                    pid=5001,
                    name="fragile_worker",
                    parent_pid=1,
                    cpu_percent=85.0,
                    memory_rss_bytes=1000 * 1024 * 1024,
                )
            )

        ctx = builder.build(
            collected_at=ts,
            resources=resources,
            processes=procs,
            health_manager=health,
        )
        scenario.append(ReplayTick(timestamp=ts, context=ctx))

    return scenario


def create_electron_saturation_scenario(
    start_time: datetime | None = None,
    num_processes: int = 50,
    ticks: int = 6,
    step_s: float = 1.0,
) -> list[ReplayTick]:
    """Genera 50 procesos Electron (Slack) bajo un mismo grupo para saturación."""
    start = start_time or datetime.now(timezone.utc)
    builder = SystemContextBuilder()
    health = SourceHealthManager()
    scenario = []

    cgroup = "/user.slice/app-gnome-slack-555.scope"
    parent_pid = 7000

    for i in range(ticks):
        ts = start + timedelta(seconds=i * step_s)
        resources = ResourceSnapshot(
            cpu_percent=88.0,
            cpu_count_logical=4,
            memory_total_bytes=16 * 1024 * 1024 * 1024,
            memory_used_bytes=12 * 1024 * 1024 * 1024,
            memory_available_bytes=4 * 1024 * 1024 * 1024,
            memory_percent=75.0,
        )
        procs = [
            ProcessSnapshot(
                pid=parent_pid,
                name="slack",
                parent_pid=1,
                executable="/usr/lib/slack/slack",
                cgroup=cgroup,
                cpu_percent=15.0,
                memory_rss_bytes=400 * 1024 * 1024,
            )
        ]
        for child_idx in range(1, num_processes):
            procs.append(
                ProcessSnapshot(
                    pid=parent_pid + child_idx,
                    name="slack",
                    parent_pid=parent_pid,
                    executable="/usr/lib/slack/slack",
                    cgroup=cgroup,
                    cmdline=f"slack --type=renderer --process-id={child_idx}",
                    cpu_percent=3.5,
                    memory_rss_bytes=150 * 1024 * 1024,
                )
            )

        ctx = builder.build(
            collected_at=ts,
            resources=resources,
            processes=procs,
            health_manager=health,
        )
        scenario.append(ReplayTick(timestamp=ts, context=ctx))

    return scenario
