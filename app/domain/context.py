"""Dominio para el contexto unificado del sistema y grupos de aplicaciones."""

from pydantic import AwareDatetime

from app.domain.base import DomainModel, NonNegativeFloat, NonNegativeInt
from app.domain.snapshots import (
    ProcessSnapshot,
    ResourceSnapshot,
    SystemPressure,
)


class ApplicationGroup(DomainModel):
    """Agrupación lógica de procesos que forman una única aplicación."""

    app_key: str
    """Identificador único estable del grupo."""

    name: str
    """Nombre visible de la aplicación deducido de forma segura."""

    processes: tuple[ProcessSnapshot, ...]
    """Procesos que componen esta aplicación."""

    cpu_percent: NonNegativeFloat = 0.0
    """Suma del uso de CPU de todos los procesos del grupo."""

    memory_rss_bytes: NonNegativeInt = 0
    """Suma de la memoria residente de todos los procesos del grupo."""


class SystemContext(DomainModel):
    """Contexto completo del sistema en un instante estructurado para análisis."""

    collected_at: AwareDatetime
    """Momento de la recolección con zona horaria."""

    resources: ResourceSnapshot
    """Uso global de recursos."""

    pressure: SystemPressure | None = None
    """Presión del sistema según PSI, si está disponible."""

    uptime_s: NonNegativeFloat | None = None
    """Segundos transcurridos desde el arranque del sistema."""

    apps: tuple[ApplicationGroup, ...] = ()
    """Aplicaciones detectadas en el sistema y sus procesos agrupados."""

    source_health: dict[str, str] = {}
    """Estado de las fuentes de datos, útil para evaluar confiabilidad."""
