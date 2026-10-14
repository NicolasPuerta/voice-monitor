"""Motor de reproducción determinista para simular y validar sesiones del monitor."""

from dataclasses import dataclass, field
from datetime import datetime
import time
from typing import Any, Sequence

from app.core.metrics import PerformanceMetrics
from app.core.pipeline import NarrationPipeline
from app.domain.enums import EventDecision
from app.domain.events import Event
from app.core.fixtures import ReplayTick


@dataclass
class ReplayResult:
    """Resultado detallado de la reproducción de una sesión."""

    total_ticks: int
    duration_s: float
    events_detected: int
    spoken_events: list[Event] = field(default_factory=list)
    deferred_events: list[Event] = field(default_factory=list)
    omitted_events: list[Event] = field(default_factory=list)
    dnd_events: list[Event] = field(default_factory=list)
    expired_events: list[Event] = field(default_factory=list)
    metrics_summary: dict[str, Any] = field(default_factory=dict)
    timeline: list[dict[str, Any]] = field(default_factory=list)


class ReplayEngine:
    """Ejecuta secuencias de estados del sistema a través de la tubería."""

    def __init__(
        self,
        pipeline: NarrationPipeline,
        metrics: PerformanceMetrics | None = None,
        speed_factor: float = 0.0,
    ) -> None:
        self.pipeline = pipeline
        self.metrics = metrics or PerformanceMetrics()
        self.speed_factor = speed_factor

    def run(self, ticks: Sequence[ReplayTick]) -> ReplayResult:
        """Reproduce la lista de ticks paso a paso de forma determinista."""
        t_start = time.perf_counter()
        spoken_events: list[Event] = []
        deferred_events: list[Event] = []
        omitted_events: list[Event] = []
        dnd_events: list[Event] = []
        expired_events: list[Event] = []
        timeline: list[dict[str, Any]] = []

        total_detected = 0

        for idx, tick in enumerate(ticks):
            # Muestrear consumo de recursos del proceso en cada tick
            self.metrics.sample_resources()

            # Inyectar eventos adicionales si el tick los define
            if tick.injected_events:
                for ev in tick.injected_events:
                    self.pipeline.grouper.add(ev, tick.timestamp)
                    total_detected += 1

            # Ejecutar el paso de la tubería con el contexto simulado
            spoken = self.pipeline.step(
                tick.timestamp, context=tick.context, metrics=self.metrics
            )

            # Clasificar eventos resultantes
            timeline_entry: dict[str, Any] = {
                "tick": idx,
                "timestamp": tick.timestamp.isoformat(),
                "apps_count": len(tick.context.apps),
                "spoken": None,
            }

            if spoken:
                if spoken.decision == EventDecision.DND:
                    dnd_events.append(spoken)
                else:
                    spoken_events.append(spoken)
                    timeline_entry["spoken"] = spoken.summary

            timeline.append(timeline_entry)

            # Simulación de tiempo real si speed_factor > 0
            if self.speed_factor > 0 and idx < len(ticks) - 1:
                next_tick = ticks[idx + 1]
                delta_s = max(
                    0.0, (next_tick.timestamp - tick.timestamp).total_seconds()
                )
                if delta_s > 0:
                    time.sleep(delta_s / self.speed_factor)

        # Capturar eventos remanentes en cola de prioridad (diferidos)
        while True:
            remaining = self.pipeline.priority_queue.pop_ready(
                ticks[-1].timestamp if ticks else datetime.now()
            )
            if not remaining:
                break
            if remaining.decision == EventDecision.EXPIRED:
                expired_events.append(remaining)
            else:
                object.__setattr__(remaining, "decision", EventDecision.DEFERRED)
                deferred_events.append(remaining)
                self.metrics.record_decision(EventDecision.DEFERRED)

        # Muestreo final de recursos
        self.metrics.sample_resources()
        total_duration = time.perf_counter() - t_start

        summary = self.metrics.get_summary()

        return ReplayResult(
            total_ticks=len(ticks),
            duration_s=round(total_duration, 4),
            events_detected=summary["counters"].get("events_detected", total_detected),
            spoken_events=spoken_events,
            deferred_events=deferred_events,
            omitted_events=omitted_events,
            dnd_events=dnd_events,
            expired_events=expired_events,
            metrics_summary=summary,
            timeline=timeline,
        )
