"""Motor de puntuacin y evaluacin de eventos."""

from datetime import datetime, timedelta

from app.domain.enums import EventPriority, EventSeverity
from app.domain.events import Event, ScoreBreakdown, ScoreResult


class ScoringEngine:
    """Calcula el score determinista de un evento y explica la decisin."""

    def __init__(self) -> None:
        # Historial para penalizar repeticin (clave -> lista de timestamps)
        self._history: dict[str, list[datetime]] = {}

    def score_event(self, event: Event, now: datetime) -> ScoreResult:
        """Asigna una puntuacin al evento basndose en factores deterministas."""
        impact = self._calc_impact(event)
        novelty = self._calc_novelty(event)
        anomaly = self._calc_anomaly(event)
        risk = self._calc_risk(event)
        relevance = self._calc_relevance(event)

        key = self._get_history_key(event)
        repetition = self._calc_repetition(key, now)

        breakdown = ScoreBreakdown(
            impact=impact,
            novelty=novelty,
            anomaly=anomaly,
            risk=risk,
            relevance=relevance,
            repetition_penalty=repetition,
        )

        total_score = breakdown.total
        priority = self._determine_priority(total_score, event.severity)
        reasons = self._generate_reasons(breakdown, priority)

        return ScoreResult(
            score=total_score,
            priority=priority,
            breakdown=breakdown,
            reasons=reasons,
        )

    def record_spoken(self, event: Event, now: datetime) -> None:
        """Registra que un evento fue hablado para aumentar su penalizacin futura."""
        key = self._get_history_key(event)
        self._history.setdefault(key, []).append(now)

    def _get_history_key(self, event: Event) -> str:
        app_key = event.metadata.app_key or "system"
        return f"{event.event_type.value}:{app_key}"

    def _calc_impact(self, event: Event) -> float:
        if event.severity == EventSeverity.CRITICAL:
            return 30.0
        if event.severity == EventSeverity.HIGH:
            return 20.0
        if event.severity == EventSeverity.MEDIUM:
            return 10.0
        if event.severity == EventSeverity.LOW:
            return 5.0
        return 0.0

    def _calc_novelty(self, event: Event) -> float:
        # Si acaba de empezar, es muy novedoso.
        dur = event.metadata.duration_s
        if dur is None:
            return 10.0
        if dur < 10.0:
            return 15.0
        if dur < 60.0:
            return 5.0
        return 0.0

    def _calc_anomaly(self, event: Event) -> float:
        # Por ahora mapeado a la confianza
        val = {"high": 15.0, "medium": 10.0, "low": 5.0}
        return val.get(event.confidence.value, 0.0)

    def _calc_risk(self, event: Event) -> float:
        # Riesgo sistmico
        if "system" in event.event_type.value or "battery" in event.event_type.value:
            return 20.0
        if event.severity in (EventSeverity.CRITICAL, EventSeverity.HIGH):
            return 10.0
        return 5.0

    def _calc_relevance(self, event: Event) -> float:
        # Procesos del usuario final importan ms que background
        name = (event.metadata.app_name or "").lower()
        foreground_hints = {"firefox", "chrome", "code", "terminal", "gnome", "discord"}
        if any(h in name for h in foreground_hints):
            return 20.0
        if name:
            return 10.0
        return 5.0

    def _calc_repetition(self, key: str, now: datetime) -> float:
        history = self._history.get(key, [])
        # Mantener slo ltimos 5 minutos
        history = [t for t in history if now - t < timedelta(minutes=5)]
        self._history[key] = history

        count = len(history)
        if count == 0:
            return 0.0
        # Crecimiento rpido de penalizacin
        return min(60.0, count * 15.0)

    def _determine_priority(self, score: float, severity: EventSeverity) -> EventPriority:
        if severity == EventSeverity.CRITICAL or score >= 70.0:
            return EventPriority.CRITICAL
        if score >= 50.0:
            return EventPriority.HIGH
        if score >= 20.0:
            return EventPriority.NORMAL
        return EventPriority.AMBIENT

    def _generate_reasons(
        self, breakdown: ScoreBreakdown, priority: EventPriority
    ) -> list[str]:
        reasons = []
        if priority == EventPriority.CRITICAL:
            reasons.append("Prioridad mxima por severidad o score excepcional.")
        if breakdown.repetition_penalty >= 30.0:
            reasons.append("Fuertemente penalizado por repeticin.")
        if breakdown.novelty > 10.0:
            reasons.append("El evento es muy reciente (alta novedad).")
        if breakdown.relevance >= 20.0:
            reasons.append("Afecta a una aplicacin interactiva del usuario.")
        return reasons
