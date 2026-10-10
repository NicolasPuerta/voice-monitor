"""Enumeraciones del dominio."""

from enum import Enum


class EventType(str, Enum):
    """Tipo de evento detectado en el sistema."""

    CPU_SPIKE = "cpu_spike"
    CPU_SUSTAINED_HIGH = "cpu_sustained_high"
    MEMORY_PRESSURE = "memory_pressure"
    SWAP_USAGE_HIGH = "swap_usage_high"
    DISK_USAGE_HIGH = "disk_usage_high"
    DISK_IO_HIGH = "disk_io_high"
    PROCESS_STARTED = "process_started"
    PROCESS_EXITED = "process_exited"
    PROCESS_RESOURCE_HIGH = "process_resource_high"
    BATTERY_LOW = "battery_low"
    BATTERY_STATE_CHANGED = "battery_state_changed"
    SYSTEM_PRESSURE = "system_pressure"


class EventSeverity(str, Enum):
    """Gravedad de un evento."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EventPriority(str, Enum):
    """Prioridad de reproduccion del evento."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    AMBIENT = "ambient"


class EventDecision(str, Enum):
    """Decision de priorizacion tomada sobre un evento."""

    SPOKEN = "spoken"
    THRESHOLD_OMITTED = "threshold_omitted"
    DEFERRED = "deferred"
    DND = "dnd"
    EXPIRED = "expired"


class ConfidenceLevel(str, Enum):
    """Confianza en que el evento detectado es real y relevante."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
