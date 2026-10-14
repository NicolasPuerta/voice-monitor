"""Detector de eventos basado en reglas simples."""

from datetime import datetime
from app.domain.context import SystemContext
from app.domain.enums import EventSeverity, EventType
from app.domain.events import Event, EventMetadata


class RuleBasedDetector:
    """Evalúa un SystemContext y genera Eventos si se superan umbrales."""

    def __init__(
        self,
        cpu_threshold: float = 85.0,
        mem_threshold: float = 90.0,
        psi_threshold: float = 20.0,
    ) -> None:
        self.cpu_threshold = cpu_threshold
        self.mem_threshold = mem_threshold
        self.psi_threshold = psi_threshold

    def detect(self, context: SystemContext, now: datetime) -> list[Event]:
        events: list[Event] = []

        # 1. System-level CPU
        cpu_pct = context.resources.cpu_percent
        if cpu_pct is not None and cpu_pct >= self.cpu_threshold:
            events.append(
                Event(
                    event_type=EventType.SYSTEM_PRESSURE,
                    severity=EventSeverity.HIGH,
                    summary=f"Carga global de CPU al {cpu_pct:.1f}%",
                    detected_at=now,
                    metadata=EventMetadata(
                        metric_name="system_cpu",
                        metric_value=cpu_pct,
                        threshold=self.cpu_threshold,
                        unit="%",
                    ),
                )
            )

        # 2. Application-level CPU
        for app in context.apps:
            if app.cpu_percent >= self.cpu_threshold:
                name = getattr(app, "display_name", getattr(app, "name", "app"))
                events.append(
                    Event(
                        event_type=EventType.CPU_SPIKE,
                        severity=EventSeverity.HIGH,
                        summary=f"Alta CPU en {name} ({app.cpu_percent:.1f}%)",
                        detected_at=now,
                        metadata=EventMetadata(
                            app_key=app.app_key,
                            app_name=name,
                            metric_name="app_cpu",
                            metric_value=app.cpu_percent,
                            threshold=self.cpu_threshold,
                            unit="%",
                        ),
                    )
                )

        # 3. System-level Memory
        mem_pct = context.resources.memory_percent
        if mem_pct is not None and mem_pct >= self.mem_threshold:
            events.append(
                Event(
                    event_type=EventType.MEMORY_PRESSURE,
                    severity=EventSeverity.HIGH,
                    summary=f"Presión de memoria alta ({mem_pct:.1f}%)",
                    detected_at=now,
                    metadata=EventMetadata(
                        metric_name="system_memory",
                        metric_value=mem_pct,
                        threshold=self.mem_threshold,
                        unit="%",
                    ),
                )
            )

        # 4. PSI Pressure
        if context.pressure and context.pressure.memory_some:
            psi_val = context.pressure.memory_some.avg10
            if psi_val >= self.psi_threshold:
                events.append(
                    Event(
                        event_type=EventType.SYSTEM_PRESSURE,
                        severity=EventSeverity.HIGH,
                        summary=f"Stall PSI memoria ({psi_val:.1f}%)",
                        detected_at=now,
                        metadata=EventMetadata(
                            metric_name="psi_memory_some_avg10",
                            metric_value=psi_val,
                            threshold=self.psi_threshold,
                            unit="%",
                        ),
                    )
                )

        return events
