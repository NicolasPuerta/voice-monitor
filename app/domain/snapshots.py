"""Modelos de las instantáneas (snapshots) del estado del sistema."""

from pydantic import AwareDatetime, Field

from app.domain.base import DomainModel, NonNegativeFloat, NonNegativeInt, Percent


class ProcessSnapshot(DomainModel):
    """Estado de un proceso en un instante dado."""

    pid: NonNegativeInt
    """Identificador del proceso."""

    name: str
    """Nombre del proceso."""

    parent_pid: NonNegativeInt | None = None
    """Identificador del proceso padre, si se conoce."""

    username: str | None = None
    """Usuario propietario del proceso, si se conoce."""

    status: str | None = None
    """Estado del proceso (por ejemplo, ``running`` o ``sleeping``)."""

    cpu_percent: NonNegativeFloat = 0.0
    """Uso de CPU; puede superar 100 en procesos con varios hilos."""

    memory_percent: Percent | None = None
    """Porcentaje de memoria física usada por el proceso, si se conoce."""

    memory_rss_bytes: NonNegativeInt | None = None
    """Memoria residente del proceso, en bytes, si está disponible."""

    num_threads: NonNegativeInt | None = None
    """Cantidad de hilos del proceso."""

    executable: str | None = None
    """Ruta del ejecutable, si está disponible."""

    cmdline: str | None = None
    """Línea de comandos sanitizada y truncada; nunca contiene la original."""

    cgroup: str | None = None
    """Ruta del cgroup del proceso, si se consultó y está disponible."""

    started_at: AwareDatetime | None = None
    """Momento en que se inició el proceso."""


class ResourceSnapshot(DomainModel):
    """Uso global de recursos del sistema en un instante dado."""

    cpu_percent: Percent
    """Uso total de CPU."""

    cpu_count_logical: int = Field(ge=1)
    """Cantidad de CPUs lógicas."""

    load_average: tuple[float, float, float] | None = None
    """Carga media a 1, 5 y 15 minutos, si está disponible."""

    memory_total_bytes: NonNegativeInt
    """Memoria física total, en bytes."""

    memory_used_bytes: NonNegativeInt
    """Memoria física en uso, en bytes."""

    memory_available_bytes: NonNegativeInt
    """Memoria disponible para nuevas aplicaciones, en bytes."""

    memory_percent: Percent
    """Porcentaje de memoria física en uso."""

    swap_total_bytes: NonNegativeInt = 0
    """Swap total, en bytes."""

    swap_used_bytes: NonNegativeInt = 0
    """Swap en uso, en bytes."""

    swap_percent: Percent = 0.0
    """Porcentaje de swap en uso."""

    disk_total_bytes: NonNegativeInt
    """Capacidad total del disco principal, en bytes."""

    disk_used_bytes: NonNegativeInt
    """Espacio usado del disco principal, en bytes."""

    disk_percent: Percent
    """Porcentaje usado del disco principal."""

    disk_read_bytes_per_s: NonNegativeFloat | None = None
    """Velocidad de lectura de disco, en bytes por segundo."""

    disk_write_bytes_per_s: NonNegativeFloat | None = None
    """Velocidad de escritura de disco, en bytes por segundo."""

    net_sent_bytes_per_s: NonNegativeFloat | None = None
    """Velocidad de envío de red, en bytes por segundo."""

    net_recv_bytes_per_s: NonNegativeFloat | None = None
    """Velocidad de recepción de red, en bytes por segundo."""

    battery_percent: Percent | None = None
    """Carga de la batería; ``None`` si el equipo no tiene batería."""

    battery_plugged: bool | None = None
    """Si el equipo está conectado a la corriente; ``None`` si se desconoce."""


class PressureStall(DomainModel):
    """Métrica PSI (Pressure Stall Information) de un recurso."""

    avg10: Percent
    """Porcentaje de tiempo con presión en los últimos 10 segundos."""

    avg60: Percent
    """Porcentaje de tiempo con presión en los últimos 60 segundos."""

    avg300: Percent
    """Porcentaje de tiempo con presión en los últimos 300 segundos."""


class SystemPressure(DomainModel):
    """Presión del sistema según PSI; cada métrica puede no estar disponible."""

    cpu_some: PressureStall | None = None
    """Presión de CPU: al menos una tarea esperando."""

    memory_some: PressureStall | None = None
    """Presión de memoria: al menos una tarea esperando."""

    memory_full: PressureStall | None = None
    """Presión de memoria: todas las tareas esperando."""

    io_some: PressureStall | None = None
    """Presión de E/S: al menos una tarea esperando."""

    io_full: PressureStall | None = None
    """Presión de E/S: todas las tareas esperando."""


class SystemSnapshot(DomainModel):
    """Instantánea completa del sistema en un instante dado."""

    collected_at: AwareDatetime
    """Momento de la recolección (con zona horaria)."""

    resources: ResourceSnapshot
    """Uso global de recursos."""

    pressure: SystemPressure | None = None
    """Presión del sistema, si el kernel la expone."""

    processes: tuple[ProcessSnapshot, ...] = ()
    """Procesos relevantes en el instante de la recolección."""

    uptime_s: NonNegativeFloat | None = None
    """Segundos transcurridos desde el arranque del sistema."""
