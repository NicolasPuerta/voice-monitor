"""Modelos de dominio para la base de conocimiento de procesos."""

from enum import Enum

from app.domain.base import DomainModel


class KnowledgeSource(str, Enum):
    """Fuentes de origen de la informacin en la base de conocimiento."""

    CURATED = "curated"
    PACKAGE_KNOWLEDGE = "package_knowledge"
    METADATA = "metadata"
    HEURISTIC = "heuristic"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class ProcessKnowledge(DomainModel):
    """Informacin estructurada sobre una aplicacin o proceso conocido."""

    key: str
    """Llave nica del proceso (ej. 'firefox', 'systemd', 'cmd:python3 /ruta')."""

    short_text: str
    """Explicacin breve y verificable."""

    long_text: str | None = None
    """Descripcin detallada (uso de recursos tpico, comportamiento esperado)."""

    category: str = "uncategorized"
    """Categora (e.g., 'browser', 'system_service', 'development')."""

    source: KnowledgeSource = KnowledgeSource.UNKNOWN
    """De dnde proviene esta explicacin."""

    confidence: str = "medium"
    """Nivel de confianza en esta identificacin."""

    version: int = 1
    """Versin de la entrada, til para migraciones."""
