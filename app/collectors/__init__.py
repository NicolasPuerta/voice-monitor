"""Collectors que observan el sistema operativo en modo solo lectura."""

from app.collectors.base import Collector
from app.collectors.health import SourceHealthManager, SourceState
from app.collectors.sanitize import sanitize_cmdline

try:
    from app.collectors.process import CollectionStats, ProcessCollector
    from app.collectors.system import (
        EnergyStateCollector,
        PSICollector,
        SystemResourceCollector,
    )
except ImportError:
    CollectionStats = None  # type: ignore[assignment,misc]
    ProcessCollector = None  # type: ignore[assignment,misc]
    EnergyStateCollector = None  # type: ignore[assignment,misc]
    PSICollector = None  # type: ignore[assignment,misc]
    SystemResourceCollector = None  # type: ignore[assignment,misc]

from app.collectors.journald import JournaldCollector
from app.collectors.systemd import SystemdCollector

__all__ = [
    "CollectionStats",
    "Collector",
    "EnergyStateCollector",
    "JournaldCollector",
    "ProcessCollector",
    "PSICollector",
    "SourceHealthManager",
    "SourceState",
    "SystemResourceCollector",
    "SystemdCollector",
    "sanitize_cmdline",
]
