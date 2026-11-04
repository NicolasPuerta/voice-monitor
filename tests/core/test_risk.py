"""Pruebas del motor de análisis de riesgos RiskEngine (MR 16)."""

from datetime import datetime, timezone

from app.core.risk import RiskEngine
from app.domain.context import ApplicationGroup, SystemContext
from app.domain.enums import EventSeverity, EventType
from app.domain.journald import (
    JournalEntry,
    JournaldEventType,
    JournaldSnapshot,
)
from app.domain.risk import RiskCategory, RiskLevel
from app.domain.snapshots import (
    PressureStall,
    ProcessSnapshot,
    ResourceSnapshot,
    SystemPressure,
)
from app.domain.systemd import ServiceState, SystemdSnapshot, UnitSnapshot

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_dummy_context(
    processes: list[ProcessSnapshot] | None = None,
    pressure: SystemPressure | None = None,
    memory_percent: float = 20.0,
    swap_percent: float = 5.0,
) -> SystemContext:
    procs = processes or []
    app = ApplicationGroup(
        app_key="test_app",
        name="test_app",
        processes=tuple(procs),
    )
    resources = ResourceSnapshot(
        cpu_percent=15.0,
        cpu_count_logical=4,
        memory_total_bytes=10_000_000_000,
        memory_used_bytes=int(10_000_000_000 * (memory_percent / 100)),
        memory_available_bytes=int(10_000_000_000 * (1 - memory_percent / 100)),
        memory_percent=memory_percent,
        swap_percent=swap_percent,
    )
    return SystemContext(
        collected_at=NOW,
        resources=resources,
        pressure=pressure,
        uptime_s=3600.0,
        apps=(app,),
    )


def test_risk_engine_oom_from_journald() -> None:
    """Verifica detección de OOM Killer a partir de eventos estructurados de journald."""
    engine = RiskEngine()
    ctx = make_dummy_context()

    oom_entry = JournalEntry(
        timestamp=NOW,
        message="kernel: Out of memory: Kill process 1234 (mysqld) score 800",
        priority=3,
        unit="mysqld.service",
        identifier="kernel",
        event_type=JournaldEventType.OOM_KILL,
    )
    journal_snap = JournaldSnapshot(
        collected_at=NOW,
        oom_events=(oom_entry,),
        total_new_entries=1,
    )

    signals = engine.evaluate(ctx, journald=journal_snap, now=NOW)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.category == RiskCategory.OOM
    assert sig.level == RiskLevel.CRITICAL
    assert "OOM Killer" in sig.title
    assert sig.evidence["unit"] == "mysqld.service"
    assert sig.confidence == "high"


def test_risk_engine_oom_from_ram_and_swap_saturation() -> None:
    """Verifica señal de riesgo inminente de OOM por RAM y Swap saturados."""
    engine = RiskEngine()
    ctx = make_dummy_context(memory_percent=99.0, swap_percent=96.0)

    signals = engine.evaluate(ctx, now=NOW)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.category == RiskCategory.OOM
    assert sig.level == RiskLevel.HIGH
    assert "Agotamiento crítico" in sig.title


def test_risk_engine_d_state_consecutive_ticks() -> None:
    """Verifica detección de procesos en estado D tras superar umbral de ticks."""
    engine = RiskEngine(d_state_ticks_threshold=2)

    proc = ProcessSnapshot(
        pid=901,
        name="rsync",
        parent_pid=1500,
        status="disk-sleep",
    )
    ctx = make_dummy_context(processes=[proc])

    # Tick 1: primer ciclo observado en D-state (por debajo del umbral 2)
    sigs_tick1 = engine.evaluate(ctx, now=NOW)
    assert len(sigs_tick1) == 0

    # Tick 2: segundo ciclo consecutivo -> emite señal
    sigs_tick2 = engine.evaluate(ctx, now=NOW)
    assert len(sigs_tick2) == 1
    sig = sigs_tick2[0]
    assert sig.category == RiskCategory.PROCESS_D_STATE
    assert sig.level == RiskLevel.HIGH
    assert sig.evidence["pid"] == 901
    assert sig.evidence["consecutive_ticks"] == 2

    # Tick 3: proceso vuelve a estado 'running' -> se limpia el historial
    proc_running = ProcessSnapshot(
        pid=901,
        name="rsync",
        parent_pid=1500,
        status="running",
    )
    ctx_recovered = make_dummy_context(processes=[proc_running])
    sigs_tick3 = engine.evaluate(ctx_recovered, now=NOW)
    assert len(sigs_tick3) == 0
    assert 901 not in engine._d_state_consecutive_ticks


def test_risk_engine_ignores_kernel_threads_in_d_state() -> None:
    """kworker (hijo de kthreadd) en estado D es rutinario, no un riesgo."""
    engine = RiskEngine(d_state_ticks_threshold=2)
    kworker = ProcessSnapshot(
        pid=12899, name="kworker/u33:0+i915_flip", parent_pid=2, status="disk-sleep"
    )
    ctx = make_dummy_context(processes=[kworker])
    assert engine.evaluate(ctx, now=NOW) == []
    assert engine.evaluate(ctx, now=NOW) == []
    assert engine.evaluate(ctx, now=NOW) == []


def test_risk_engine_zombie_accumulation() -> None:
    """Verifica detección de acumulación anómala de zombis superando umbrales."""
    engine = RiskEngine(zombie_threshold=3)

    # 1. Menos de 3 zombis: no genera señal (transitorio normal)
    procs_under = [
        ProcessSnapshot(pid=10, name="z1", parent_pid=1, status="zombie"),
        ProcessSnapshot(pid=11, name="z2", parent_pid=1, status="zombie"),
    ]
    sigs_under = engine.evaluate(make_dummy_context(processes=procs_under), now=NOW)
    assert len(sigs_under) == 0

    # 2. 3 zombis: genera señal nivel MEDIUM con identificación del padre
    procs_3 = procs_under + [
        ProcessSnapshot(pid=12, name="z3", parent_pid=1, status="zombie")
    ]
    sigs_3 = engine.evaluate(make_dummy_context(processes=procs_3), now=NOW)
    assert len(sigs_3) == 1
    assert sigs_3[0].category == RiskCategory.ZOMBIE
    assert sigs_3[0].level == RiskLevel.MEDIUM
    assert sigs_3[0].evidence["count"] == 3
    assert sigs_3[0].evidence["parent_pids"] == [1]

    # 3. >= 5 zombis: escala a nivel HIGH
    procs_5 = procs_3 + [
        ProcessSnapshot(pid=13, name="z4", parent_pid=1, status="zombie"),
        ProcessSnapshot(pid=14, name="z5", parent_pid=1, status="zombie"),
    ]
    sigs_5 = engine.evaluate(make_dummy_context(processes=procs_5), now=NOW)
    assert len(sigs_5) == 1
    assert sigs_5[0].level == RiskLevel.HIGH


def test_risk_engine_extreme_psi_pressure() -> None:
    """Verifica señal de riesgo por estancamiento severo de tareas (PSI)."""
    engine = RiskEngine(psi_extreme_threshold=50.0)

    val_some = PressureStall(avg10=55.0, avg60=40.0, avg300=30.0)
    val_full = PressureStall(avg10=35.0, avg60=25.0, avg300=15.0)
    psi = SystemPressure(memory_some=val_some, memory_full=val_full)

    ctx = make_dummy_context(pressure=psi)
    signals = engine.evaluate(ctx, now=NOW)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.category == RiskCategory.EXTREME_PRESSURE
    assert sig.level == RiskLevel.CRITICAL
    assert "Memoria" in sig.evidence["breakdown"][0]


def _systemd_snapshot(*failed: str) -> SystemdSnapshot:
    units = tuple(
        UnitSnapshot(
            name=name,
            active_state=ServiceState.FAILED,
            sub_state="failed",
            unit_type="service",
        )
        for name in failed
    )
    return SystemdSnapshot(
        collected_at=NOW,
        units_total=len(units),
        units_failed=len(units),
        failed_units=units,
    )


def _journal_failure(unit: str, identifier: str = "systemd") -> JournaldSnapshot:
    entry = JournalEntry(
        timestamp=NOW,
        message=f"{unit}: Failed with result 'exit-code'.",
        priority=4,
        unit=unit,
        identifier=identifier,
        event_type=JournaldEventType.SERVICE_FAILURE,
    )
    return JournaldSnapshot(collected_at=NOW, service_failures=(entry,))


def at(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def test_risk_engine_service_flapping_sliding_window() -> None:
    """Sin journald, cuenta transiciones a failed de systemd dentro de la ventana."""
    engine = RiskEngine(flapping_window_s=60.0, flapping_threshold=2)
    ctx = make_dummy_context()
    failed = _systemd_snapshot("web.service")
    healthy = _systemd_snapshot()

    # Línea base: lo que ya estaba caído al arrancar no se anuncia
    assert engine.evaluate(ctx, systemd=healthy, now=at(90)) == []

    # 1. Primera caída: se anuncia como fallo simple
    sigs1 = engine.evaluate(ctx, systemd=failed, now=at(100))
    assert [s.category for s in sigs1] == [RiskCategory.SERVICE_FAILURE]
    assert sigs1[0].service_name == "web.service"

    # Sigue caído: no es un fallo nuevo
    assert engine.evaluate(ctx, systemd=failed, now=at(105)) == []

    # 2. Se recupera y vuelve a caer dentro de la ventana: flapping
    assert engine.evaluate(ctx, systemd=healthy, now=at(110)) == []
    sigs2 = engine.evaluate(ctx, systemd=failed, now=at(120))
    assert len(sigs2) == 1
    assert sigs2[0].category == RiskCategory.REPEATED_FAILURES
    assert sigs2[0].level == RiskLevel.HIGH
    assert sigs2[0].evidence["failure_count"] == 2

    # 3. Nueva caída 80 s después (fuera de ventana): vuelve a ser fallo simple
    assert engine.evaluate(ctx, systemd=healthy, now=at(190)) == []
    sigs3 = engine.evaluate(ctx, systemd=failed, now=at(200))
    assert [s.category for s in sigs3] == [RiskCategory.SERVICE_FAILURE]


def test_risk_engine_unit_already_failed_at_startup_is_silent() -> None:
    engine = RiskEngine()
    ctx = make_dummy_context()
    failed = _systemd_snapshot("old.service")
    assert engine.evaluate(ctx, systemd=failed, now=at(0)) == []
    assert engine.evaluate(ctx, systemd=failed, now=at(5)) == []


def test_risk_engine_prefers_journald_and_does_not_double_count() -> None:
    """Con journald, una caída vista también por systemd cuenta una sola vez."""
    engine = RiskEngine(flapping_window_s=60.0, flapping_threshold=2)
    ctx = make_dummy_context()
    empty_journal = JournaldSnapshot(collected_at=NOW)
    engine.evaluate(ctx, systemd=_systemd_snapshot(), journald=empty_journal, now=at(0))

    sigs1 = engine.evaluate(
        ctx,
        systemd=_systemd_snapshot(),
        journald=_journal_failure("web.service"),
        now=at(1),
    )
    assert [s.category for s in sigs1] == [RiskCategory.SERVICE_FAILURE]

    # El siguiente tick systemd ya la ve en failed: no suma otro fallo
    sigs2 = engine.evaluate(
        ctx, systemd=_systemd_snapshot("web.service"), journald=empty_journal, now=at(6)
    )
    assert sigs2 == []


def test_risk_engine_restart_loop_from_journald_is_flapping() -> None:
    """Reinicios automáticos (nunca quedan en failed) se detectan por journald."""
    engine = RiskEngine(flapping_window_s=60.0, flapping_threshold=2)
    ctx = make_dummy_context()
    engine.evaluate(ctx, journald=_journal_failure("loop.service"), now=at(0))
    sigs = engine.evaluate(ctx, journald=_journal_failure("loop.service"), now=at(10))
    assert [s.category for s in sigs] == [RiskCategory.REPEATED_FAILURES]


def test_risk_engine_ignores_failure_words_from_other_apps() -> None:
    engine = RiskEngine()
    ctx = make_dummy_context()
    journal = _journal_failure("myapp.service", identifier="myapp")
    assert engine.evaluate(ctx, journald=journal, now=at(0)) == []


def test_service_failure_signal_maps_to_service_failed_event() -> None:
    engine = RiskEngine()
    signals = engine.evaluate(
        make_dummy_context(), journald=_journal_failure("web.service"), now=NOW
    )
    events = engine.signals_to_events(signals)
    assert [e.event_type for e in events] == [EventType.SERVICE_FAILED]
    assert events[0].metadata.app_name == "web.service"


def test_risk_engine_signals_to_events_mapping() -> None:
    """Verifica conversión fiable de RiskSignal a Event para el pipeline."""
    oom_entry = JournalEntry(
        timestamp=NOW,
        message="Out of memory: Kill process",
        priority=3,
        event_type=JournaldEventType.OOM_KILL,
    )
    snap = JournaldSnapshot(collected_at=NOW, oom_events=(oom_entry,))
    engine = RiskEngine()
    signals = engine.evaluate(make_dummy_context(), journald=snap, now=NOW)

    events = engine.signals_to_events(signals)
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == EventType.OOM_KILL
    assert ev.severity == EventSeverity.CRITICAL
    assert ev.metadata.extra["risk_category"] == "oom"


def test_risk_engine_is_strictly_read_only() -> None:
    """Verifica que el motor de riesgos no modifique el sistema ni ejecute acciones."""
    import inspect

    methods = [
        name
        for name, _ in inspect.getmembers(RiskEngine, predicate=inspect.isfunction)
    ]
    forbidden_words = ["kill", "terminate", "stop", "restart", "run", "exec"]
    for m in methods:
        for word in forbidden_words:
            assert word not in m.lower(), f"Método prohibido encontrado: {m}"
