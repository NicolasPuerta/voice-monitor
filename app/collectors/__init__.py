"""Collectors que observan el sistema operativo en modo solo lectura."""

from app.collectors.base import Collector
from app.collectors.process import CollectionStats, ProcessCollector
from app.collectors.sanitize import sanitize_cmdline
from app.collectors.health import SourceHealthManager, SourceState
from app.collectors.system import (
    EnergyStateCollector,
    PSICollector,
    SystemResourceCollector,
)

__all__ = [
    "CollectionStats",
    "Collector",
    "EnergyStateCollector",
    "ProcessCollector",
    "PSICollector",
    "SourceHealthManager",
    "SourceState",
    "SystemResourceCollector",
    "sanitize_cmdline",
]
