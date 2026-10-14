"""Modelos de dominio para señales y riesgos estructurados (RiskEngine)."""

from enum import Enum
from typing import Any

from pydantic import AwareDatetime, Field

from app.domain.base import DomainModel


class RiskCategory(str, Enum):
    """Categoría de la señal de riesgo detectada."""

    OOM = "oom"
    PROCESS_D_STATE = "process_d_state"
    ZOMBIE = "zombie"
    EXTREME_PRESSURE = "extreme_pressure"
    REPEATED_FAILURES = "repeated_failures"


class RiskLevel(str, Enum):
    """Nivel de severidad asignado a la señal de riesgo."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskSignal(DomainModel):
    """Señal estructurada de riesgo basada exclusivamente en evidencias comprobables."""

    category: RiskCategory
    level: RiskLevel
    title: str
    description: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    detected_at: AwareDatetime
    app_key: str | None = None
    service_name: str | None = None
    confidence: str = "high"
