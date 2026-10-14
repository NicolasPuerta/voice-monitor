"""Motor de análisis de riesgos y señales avanzadas del sistema (MR 16).

Evalúa de forma puramente observacional y basada en evidencias:
- Eventos OOM (Out of Memory killer).
- Procesos en estado D (espera no interrumpible / disk-sleep).
- Acumulación de procesos zombies.
- Presión extrema de recursos (PSI).
- Bucles de fallos repetidos y flapping de servicios.

No ejecuta acciones correctivas ni modifica procesos.
"""

from collections import defaultdict
from datetime import datetime, timezone
import logging
import uuid

from app.domain.context import SystemContext
from app.domain.enums import (
    ConfidenceLevel,
    EventSeverity,
    EventType,
)
from app.domain.events import Event, EventMetadata
from app.domain.journald import JournaldSnapshot
from app.domain.snapshots import ProcessSnapshot
from app.domain.risk import RiskCategory, RiskLevel, RiskSignal
from app.domain.systemd import SystemdSnapshot

logger = logging.getLogger(__name__)


class RiskEngine:
    """Evalúa el estado del sistema y produce señales de riesgo estructuradas."""

    def __init__(
        self,
        flapping_window_s: float = 300.0,
        flapping_threshold: int = 2,
        zombie_threshold: int = 3,
        d_state_ticks_threshold: int = 2,
        psi_extreme_threshold: float = 50.0,
    ) -> None:
        self.flapping_window_s = flapping_window_s
        self.flapping_threshold = flapping_threshold
        self.zombie_threshold = zombie_threshold
        self.d_state_ticks_threshold = d_state_ticks_threshold
        self.psi_extreme_threshold = psi_extreme_threshold

        # Historial de fallos por servicio: service_name -> list[timestamps]
        self._service_failure_history: dict[str, list[datetime]] = defaultdict(list)

        # Historial de procesos en estado D: pid -> ticks consecutivos
        self._d_state_consecutive_ticks: dict[int, int] = defaultdict(int)

    def evaluate(
        self,
        context: SystemContext,
        systemd: SystemdSnapshot | None = None,
        journald: JournaldSnapshot | None = None,
        now: datetime | None = None,
    ) -> list[RiskSignal]:
        """Evalúa todas las fuentes y genera señales basadas en evidencia."""
        eval_time = datetime.now(timezone.utc) if now is None else now
        signals: list[RiskSignal] = []

        # 1. Señales de OOM Killer
        signals.extend(self._evaluate_oom(context, journald, eval_time))

        # 2. Señales de procesos en Estado D (espera no interrumpible de E/S)
        signals.extend(self._evaluate_d_state(context, eval_time))

        # 3. Señales de acumulación de procesos zombis
        signals.extend(self._evaluate_zombies(context, eval_time))

        # 4. Señales de presión extrema de recursos (PSI)
        signals.extend(self._evaluate_extreme_pressure(context, eval_time))

        # 5. Señales de fallos repetidos / flapping de servicios
        signals.extend(self._evaluate_repeated_failures(systemd, journald, eval_time))

        return signals

    def _evaluate_oom(
        self,
        context: SystemContext,
        journald: JournaldSnapshot | None,
        now: datetime,
    ) -> list[RiskSignal]:
        """Detecta eventos confirmados de OOM en journald o saturación inminente."""
        signals: list[RiskSignal] = []

        # Evidencia directa de OOM killer en journald
        if journald and journald.oom_events:
            for oom_ev in journald.oom_events:
                signals.append(
                    RiskSignal(
                        category=RiskCategory.OOM,
                        level=RiskLevel.CRITICAL,
                        title="Invocación confirmada del OOM Killer del Kernel",
                        description=(
                            "El kernel de Linux activó el Out of Memory killer "
                            "para terminar procesos por agotamiento de memoria."
                        ),
                        evidence={
                            "message": oom_ev.message,
                            "unit": oom_ev.unit,
                            "identifier": oom_ev.identifier,
                            "timestamp": oom_ev.timestamp.isoformat(),
                        },
                        detected_at=oom_ev.timestamp,
                        confidence="high",
                    )
                )

        # Evidencia de saturación física extrema (RAM + Swap al límite)
        res = context.resources
        swap_pct = getattr(res, "swap_percent", None)
        if res.memory_percent >= 98.0 and (swap_pct is None or swap_pct >= 95.0):
            signals.append(
                RiskSignal(
                    category=RiskCategory.OOM,
                    level=RiskLevel.HIGH,
                    title="Agotamiento crítico de Memoria y Swap",
                    description=(
                        "Uso de memoria física superior al 98% con swap saturado. "
                        "Riesgo inminente de activación del OOM killer."
                    ),
                    evidence={
                        "memory_percent": res.memory_percent,
                        "swap_percent": swap_pct,
                    },
                    detected_at=now,
                    confidence="high",
                )
            )

        return signals

    def _evaluate_d_state(
        self, context: SystemContext, now: datetime
    ) -> list[RiskSignal]:
        """Detecta procesos bloqueados en espera no interrumpible de E/S (Estado D)."""
        signals: list[RiskSignal] = []
        active_d_pids = set()

        all_processes: list[ProcessSnapshot] = []
        for app in context.apps:
            all_processes.extend(app.processes)

        for proc in all_processes:
            st = (proc.status or "").lower()
            if st in ("disk-sleep", "d"):
                active_d_pids.add(proc.pid)
                self._d_state_consecutive_ticks[proc.pid] += 1
                ticks = self._d_state_consecutive_ticks[proc.pid]

                if ticks >= self.d_state_ticks_threshold:
                    signals.append(
                        RiskSignal(
                            category=RiskCategory.PROCESS_D_STATE,
                            level=RiskLevel.HIGH,
                            title=f"Proceso '{proc.name}' bloqueado en Estado D",
                            description=(
                                f"El proceso '{proc.name}' (PID: {proc.pid}) permanece "
                                f"en espera no interrumpible de E/S por {ticks} ciclos."
                            ),
                            evidence={
                                "pid": proc.pid,
                                "name": proc.name,
                                "status": proc.status,
                                "consecutive_ticks": ticks,
                            },
                            detected_at=now,
                            app_key=proc.name,
                            confidence="high",
                        )
                    )

        # Limpiar pids que ya no están en estado D
        for pid in list(self._d_state_consecutive_ticks.keys()):
            if pid not in active_d_pids:
                del self._d_state_consecutive_ticks[pid]

        return signals

    def _evaluate_zombies(
        self, context: SystemContext, now: datetime
    ) -> list[RiskSignal]:
        """Detecta acumulación anómala de procesos zombis."""
        signals: list[RiskSignal] = []
        zombies = []

        for app in context.apps:
            for proc in app.processes:
                st = (proc.status or "").lower()
                if st in ("zombie", "z"):
                    zombies.append(proc)

        if len(zombies) >= self.zombie_threshold:
            parent_pids = list({z.parent_pid for z in zombies if z.parent_pid})
            level = RiskLevel.HIGH if len(zombies) >= 5 else RiskLevel.MEDIUM
            signals.append(
                RiskSignal(
                    category=RiskCategory.ZOMBIE,
                    level=level,
                    title=f"Acumulación anómala de {len(zombies)} procesos zombi",
                    description=(
                        f"Se observaron {len(zombies)} procesos zombis en el sistema. "
                        "El proceso padre no está recolectando los estados de salida."
                    ),
                    evidence={
                        "count": len(zombies),
                        "pids": [z.pid for z in zombies[:10]],
                        "parent_pids": parent_pids,
                    },
                    detected_at=now,
                    confidence="high",
                )
            )

        return signals

    def _evaluate_extreme_pressure(
        self, context: SystemContext, now: datetime
    ) -> list[RiskSignal]:
        """Detecta estancamiento severo de recursos según métricas PSI del kernel."""
        signals: list[RiskSignal] = []
        press = context.pressure
        if press is None:
            return signals

        details = []
        level = RiskLevel.HIGH

        if press.memory_some or press.memory_full:
            some_avg = press.memory_some.avg10 if press.memory_some else 0.0
            full_avg = press.memory_full.avg10 if press.memory_full else 0.0
            if some_avg >= self.psi_extreme_threshold or full_avg >= 25.0:
                details.append(
                    f"Memoria (some: {some_avg:.1f}%, full: {full_avg:.1f}%)"
                )
                if full_avg >= 30.0:
                    level = RiskLevel.CRITICAL

        if press.io_some or press.io_full:
            some_avg = press.io_some.avg10 if press.io_some else 0.0
            full_avg = press.io_full.avg10 if press.io_full else 0.0
            if some_avg >= self.psi_extreme_threshold or full_avg >= 30.0:
                details.append(
                    f"E/S Disco (some: {some_avg:.1f}%, full: {full_avg:.1f}%)"
                )
                if full_avg >= 40.0:
                    level = RiskLevel.CRITICAL

        if press.cpu_some:
            some_avg = press.cpu_some.avg10
            if some_avg >= 65.0:
                details.append(f"CPU (some: {some_avg:.1f}%)")

        if details:
            breakdown_str = ", ".join(details)
            signals.append(
                RiskSignal(
                    category=RiskCategory.EXTREME_PRESSURE,
                    level=level,
                    title="Presión extrema en recursos del sistema (PSI)",
                    description=(
                        f"Estancamiento severo de tareas por escasez de recursos: "
                        f"{breakdown_str}."
                    ),
                    evidence={
                        "breakdown": details,
                        "cpu_load": context.resources.load_average,
                    },
                    detected_at=now,
                    confidence="high",
                )
            )

        return signals

    def _evaluate_repeated_failures(
        self,
        systemd: SystemdSnapshot | None,
        journald: JournaldSnapshot | None,
        now: datetime,
    ) -> list[RiskSignal]:
        """Detecta bucles de reinicio continuo o fallos recurrentes de servicios."""
        signals: list[RiskSignal] = []
        current_failed: set[str] = set()

        # Registrar fallos observados en systemd
        if systemd:
            for u in systemd.failed_units:
                current_failed.add(u.name)

        # Registrar caídas observadas en journald
        if journald:
            for f in journald.service_failures:
                if f.unit:
                    current_failed.add(f.unit)

        # Actualizar historial y podar entradas antiguas fuera de la ventana
        cutoff = now.timestamp() - self.flapping_window_s
        for unit_name in current_failed:
            history = self._service_failure_history[unit_name]
            history.append(now)
            # Mantener solo los de la ventana
            fresh = [t for t in history if t.timestamp() >= cutoff]
            self._service_failure_history[unit_name] = fresh

            if len(fresh) >= self.flapping_threshold:
                mins = int(self.flapping_window_s // 60)
                signals.append(
                    RiskSignal(
                        category=RiskCategory.REPEATED_FAILURES,
                        level=RiskLevel.HIGH,
                        title=f"Bucle de fallos recurrentes en '{unit_name}'",
                        description=(
                            f"El servicio '{unit_name}' ha fallado {len(fresh)} veces "
                            f"en los últimos {mins} minutos."
                        ),
                        evidence={
                            "service": unit_name,
                            "failure_count": len(fresh),
                            "window_minutes": mins,
                        },
                        detected_at=now,
                        service_name=unit_name,
                        app_key=unit_name,
                        confidence="high",
                    )
                )

        return signals

    @staticmethod
    def signals_to_events(signals: list[RiskSignal]) -> list[Event]:
        """Convierte señales de riesgo en eventos del dominio aptos para el pipeline."""
        events: list[Event] = []
        type_mapping = {
            RiskCategory.OOM: EventType.OOM_KILL,
            RiskCategory.PROCESS_D_STATE: EventType.PROCESS_UNINTERRUPTIBLE_SLEEP,
            RiskCategory.ZOMBIE: EventType.ZOMBIE_ACCUMULATION,
            RiskCategory.EXTREME_PRESSURE: EventType.EXTREME_PRESSURE,
            RiskCategory.REPEATED_FAILURES: EventType.SERVICE_FLAPPING,
        }
        severity_mapping = {
            RiskLevel.CRITICAL: EventSeverity.CRITICAL,
            RiskLevel.HIGH: EventSeverity.HIGH,
            RiskLevel.MEDIUM: EventSeverity.MEDIUM,
            RiskLevel.LOW: EventSeverity.LOW,
        }

        for s in signals:
            ev_type = type_mapping.get(s.category, EventType.RISK_SIGNAL)
            ev_sev = severity_mapping.get(s.level, EventSeverity.HIGH)

            extra_info = {
                "risk_category": s.category.value,
                "risk_title": s.title,
                **{f"evidence_{k}": str(v) for k, v in s.evidence.items()},
            }

            event = Event(
                id=uuid.uuid4(),
                event_type=ev_type,
                severity=ev_sev,
                confidence=ConfidenceLevel.HIGH,
                summary=f"{s.title}: {s.description}",
                detected_at=s.detected_at,
                metadata=EventMetadata(
                    app_key=s.app_key or s.service_name or "kernel",
                    app_name=s.service_name or s.app_key or "Sistema",
                    extra=extra_info,
                ),
            )
            events.append(event)

        return events
