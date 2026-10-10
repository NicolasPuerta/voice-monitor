"""Detector de eventos basado en reglas simples."""

from datetime import datetime
from app.domain.events import Event, EventMetadata
from app.domain.enums import EventType, EventSeverity
from app.domain.context import SystemContext


class RuleBasedDetector:
    """Evalua un SystemContext y genera Eventos si se superan umbrales."""

    def __init__(self, cpu_threshold: float = 85.0, mem_threshold: float = 90.0):
        self.cpu_threshold = cpu_threshold
        self.mem_threshold = mem_threshold

    def detect(self, context: SystemContext, now: datetime) -> list[Event]:
        events = []

        # 1. System-level CPU
        if (
            context.resources.cpu_percent
            and context.resources.cpu_percent >= self.cpu_threshold
        ):
            events.append(
                Event(
                    event_type=EventType.SYSTEM_PRESSURE,
                    severity=EventSeverity.HIGH,
                    summary=f"Carga global de CPU al {context.resources.cpu_percent:.1f}%",
                    detected_at=now,
                    metadata=EventMetadata(
                        metric_name="system_cpu",
                        metric_value=context.resources.cpu_percent,
                        threshold=self.cpu_threshold,
                        unit="%",
                    ),
                )
            )

        # 2. Application-level CPU
        for app in context.apps:
            if app.cpu_percent >= self.cpu_threshold:
                events.append(
                    Event(
                        event_type=EventType.CPU_SPIKE,
                        severity=EventSeverity.HIGH,
                        summary=f"Alta CPU en {app.display_name} ({app.cpu_percent:.1f}%)",
                        detected_at=now,
                        metadata=EventMetadata(
                            app_key=app.app_key,
                            app_name=app.display_name,
                            metric_name="app_cpu",
                            metric_value=app.cpu_percent,
                            threshold=self.cpu_threshold,
                            unit="%",
                        ),
                    )
                )

        return events
