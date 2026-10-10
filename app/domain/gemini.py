"""Modelos de dominio exclusivos para la integracin con Gemini."""

from pydantic import Field

from app.domain.base import DomainModel


class SafeEventSummary(DomainModel):
    """Resumen seguro de un evento, despojado de metadatos profundos."""

    event_type: str
    severity: str
    priority: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    app_key: str
    app_name: str
    summary: str
    duration_s: float | None = None


class GeminiContext(DomainModel):
    """Contexto delimitado y seguro que se enva a la API de Gemini."""

    system_load_avg: tuple[float, float, float]
    memory_percent: float
    battery_percent: float | None = None
    battery_plugged: bool | None = None

    # Evento primario que motiva la llamada
    primary_event: SafeEventSummary

    # Otros eventos recientes (para contexto, deduplicados y limitados)
    recent_events: list[SafeEventSummary] = Field(default_factory=list)

    # Explicacin de la KB de procesos, si se conoce
    process_knowledge: str | None = None


class AnalysisResult(DomainModel):
    """Resultado estructurado del anlisis devuelto por Gemini."""
    
    summary: str
    """Resumen extremadamente breve de qu pas."""
    
    explanation: str
    """Explicacin de la causa (admitiendo si no se tienen datos suficientes)."""
    
    impact: str
    """Impacto real estimado para el sistema o usuario."""
    
    confidence: str
    """Nivel de certeza en el anlisis (alta, media, baja)."""
    
    risk: str
    """Riesgo derivado si se ignora el evento."""
    
    speech_text: str
    """Texto conciso diseado para ser ledo en voz alta al usuario."""
