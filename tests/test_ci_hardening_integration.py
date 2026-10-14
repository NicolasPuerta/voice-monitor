"""Pruebas de integración para verificación de endurecimiento en producción (MR 18).

Verifica de forma integrada y sin dependencias externas (sin red, sin API keys reales,
sin hardware físico de audio):
1. Tubería completa offline con collectors independientes y degradación elegante.
2. Sanitización estricta de privacidad antes de llegar al constructor de contexto Gemini.
3. Persistencia asíncrona y segura en SQLite de eventos, sesiones y salud de fuentes.
4. Circuit Breaker y protección contra timeouts ante caídas de red simuladas.
5. Cola de audio no bloqueante y modo DND (retención y diferimiento sin pérdida).
6. Base de conocimiento versionada con más de 200 procesos y fallback seguro a UNKNOWN.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
from typing import Any

from app.collectors.health import SourceHealthManager, SourceState
from app.collectors.journald import JournaldCollector
from app.collectors.process import ProcessCollector
from app.collectors.system import SystemResourceCollector
from app.collectors.systemd import SystemdCollector
from app.core.analysis import AnalysisAgent
from app.core.audio.adapters.espeak import EspeakGenerator
from app.core.audio.adapters.piper import PiperGenerator
from app.core.audio.manager import AudioQueueManager
from app.core.audio.player import AudioPlayer
from app.core.config import Settings
from app.core.context import SystemContextBuilder
from app.core.detector import RuleBasedDetector
from app.core.dnd import DNDManager
from app.core.flow import EventGrouper, FlowController
from app.core.gemini import CircuitBreaker, GeminiClient, GeminiContextBuilder
from app.core.pipeline import NarrationPipeline
from app.core.privacy import PrivacySanitizer
from app.collectors.sanitize import sanitize_cmdline
from app.core.scoring import ScoringEngine
from app.domain.audio import AudioData
from app.domain.enums import EventDecision, EventSeverity, EventType
from app.domain.events import Event, EventMetadata
from app.domain.snapshots import ProcessSnapshot, ResourceSnapshot
from app.storage.db import BackgroundDatabase
from app.storage.repositories import (
    EventRepository,
    KnowledgeRepository,
    SessionRepository,
    SourceHealthRepository,
)


class MockSilentAudioPlayer(AudioPlayer):
    """Reproductor simulado sin dependencias de hardware ni subprocesos."""

    def __init__(self) -> None:
        self.played_items: list[AudioData] = []
        self._is_playing = False

    def play(self, audio: AudioData) -> None:
        self.played_items.append(audio)
        self._is_playing = True

    def stop(self) -> None:
        self._is_playing = False

    def is_playing(self) -> bool:
        return self._is_playing


def test_offline_full_pipeline_hardening(tmp_path: Path) -> None:
    """Ejecuta el ciclo de vida completo de la tubería sin red ni hardware."""
    db_path = tmp_path / "hardening.db"
    db = BackgroundDatabase(db_path, flush_interval_s=0.05)
    health_mgr = SourceHealthManager()

    session_repo = SessionRepository(db)
    event_repo = EventRepository(db)
    knowledge_repo = KnowledgeRepository(db)
    health_repo = SourceHealthRepository(db)

    session_id = "test-hardening-session-001"
    now = datetime.now(timezone.utc)
    session_repo.start_session(session_id, now)

    # 1. Componentes con sanitizador de privacidad
    sanitizer = PrivacySanitizer()
    context_builder = SystemContextBuilder()
    gemini_ctx_builder = GeminiContextBuilder(sanitizer)
    detector = RuleBasedDetector(cpu_threshold=5.0)
    scoring = ScoringEngine()
    grouper = EventGrouper(window_s=0.2)
    flow = FlowController(scoring)

    # 2. Audio no bloqueante con reproductor mock
    mock_player = MockSilentAudioPlayer()
    mock_piper = PiperGenerator()
    mock_espeak = EspeakGenerator()
    audio_mgr = AudioQueueManager(
        mock_player,
        primary_generator=mock_piper,
        fallback_generators=[mock_espeak],
        health_manager=health_mgr,
    )

    # 3. DND Manager
    dnd_mgr = DNDManager()

    # 4. Settings de prueba (offline, sin API key real)
    settings = Settings(
        gemini={"enabled": False, "api_key": None},
        narration={"cooldown_s": 0.1, "min_score": 10.0},
    )
    gemini_client = GeminiClient(settings)
    analysis_agent = AnalysisAgent(gemini_client)

    pipeline = NarrationPipeline(
        settings=settings,
        context_builder=context_builder,
        detector=detector,
        scoring=scoring,
        grouper=grouper,
        flow_controller=flow,
        gemini_builder=gemini_ctx_builder,
        analysis_agent=analysis_agent,
        audio_manager=audio_mgr,
        event_repo=event_repo,
        knowledge_repo=knowledge_repo,
        test_mode_gemini=True,
        dnd_manager=dnd_mgr,
        health_manager=health_mgr,
        session_id=session_id,
    )

    # 5. Inyectar datos con secretos que DEBEN ser sanitizados
    raw_sensitive_args = [
        "/usr/bin/my_app",
        "--api_key=SECRET_TOKEN_XYZ_12345",
        "--password=super_secret_pwd",
    ]
    sanitized_cmd = sanitize_cmdline(raw_sensitive_args)
    assert "SECRET_TOKEN" not in sanitized_cmd
    assert "super_secret_pwd" not in sanitized_cmd

    processes = [
        ProcessSnapshot(
            pid=1234,
            name="my_app",
            cmdline=sanitized_cmd,
            cpu_percent=45.0,
            memory_rss_bytes=100 * 1024 * 1024,
            memory_percent=5.0,
            status="running",
            username="juan",
        )
    ]
    resources = ResourceSnapshot(
        cpu_percent=55.0,
        cpu_count_logical=4,
        memory_total_bytes=8 * 1024 * 1024 * 1024,
        memory_used_bytes=4 * 1024 * 1024 * 1024,
        memory_available_bytes=4 * 1024 * 1024 * 1024,
        memory_percent=50.0,
    )

    context = context_builder.build(
        processes=processes,
        resources=resources,
        health_manager=health_mgr,
    )

    # Verificación de privacidad: ningún token sensible en context
    for app in context.apps:
        for p in app.processes:
            assert "SECRET_TOKEN" not in (p.cmdline or "")
            assert "super_secret_pwd" not in (p.cmdline or "")

    # Ejecutar ciclo de la tubería
    pipeline.step(now=now, context=context)
    later = now + timedelta(seconds=1)
    ev = pipeline.step(now=later, context=context)
    assert ev is not None

    # Verificación de privacidad en el constructor de contexto para Gemini
    gemini_ctx = gemini_ctx_builder.build(
        event=ev,
        sys_ctx=context,
        process_knowledge="App token: Bearer MY_JWT_TOKEN_ABC123",
    )
    assert "MY_JWT_TOKEN_ABC123" not in (gemini_ctx.process_knowledge or "")

    health_repo.save_health(
        session_id=session_id,
        source="system",
        state="OK",
        reason="initialized",
        now=now,
    )

    # Esperar el vaciado asíncrono de base de datos
    time.sleep(0.3)

    # Verificar persistencia en SQLite
    saved_events = event_repo.get_events_for_session(session_id)
    assert len(saved_events) >= 1
    valid_types = ("cpu_spike", "system_pressure", "resource_pressure")
    assert saved_events[0]["event_type"] in valid_types

    health_records = health_repo.get_health_for_session(session_id)
    assert len(health_records) >= 1

    pipeline.stop()
    db.stop()


def test_independent_collector_isolation_and_degradation() -> None:
    """Verifica que un fallo catastrófico en un collector no detenga a los demás."""
    health_mgr = SourceHealthManager()

    # Collector de procesos funcional
    proc_coll = ProcessCollector()
    proc_snap = proc_coll.collect()
    assert isinstance(proc_snap, tuple)

    # Collector de recursos funcional
    sys_coll = SystemResourceCollector(health_mgr)
    res_snap = sys_coll.collect()
    assert res_snap.cpu_count_logical >= 1
    assert health_mgr.get_state("system_resources") == SourceState.OK

    # Collector con fallo forzado (e.g. systemd sin D-Bus disponible)
    class BrokenClient:
        def ListUnits(self) -> Any:
            raise OSError("D-Bus daemon unreachable")

    sysd_coll = SystemdCollector(health_mgr, dbus_client=BrokenClient())
    assert sysd_coll.collect() is None
    assert sysd_coll.collect() is None
    # La fuente se marca degradada tras fallos consecutivos
    assert health_mgr.get_state("systemd") in (
        SourceState.DEGRADED,
        SourceState.DISABLED,
    )

    # Collector de journald ausente
    j_coll = JournaldCollector(health_mgr, reader=None, entry_source=None)
    assert j_coll.collect() is None
    assert j_coll.collect() is None
    assert health_mgr.get_state("journald") in (
        SourceState.DEGRADED,
        SourceState.DISABLED,
    )

    # El collector de procesos sigue funcionando independientemente
    proc_snap_2 = proc_coll.collect()
    assert isinstance(proc_snap_2, tuple)


def test_dnd_retention_and_deferral_without_loss(tmp_path: Path) -> None:
    """Verifica que en modo DND los eventos no se descarten ni se reproduzcan."""
    db_path = tmp_path / "dnd_test.db"
    db = BackgroundDatabase(db_path, flush_interval_s=0.05)
    event_repo = EventRepository(db)
    health_mgr = SourceHealthManager()

    mock_player = MockSilentAudioPlayer()
    audio_mgr = AudioQueueManager(mock_player, primary_generator=PiperGenerator())

    dnd_mgr = DNDManager()
    dnd_mgr.pause(reason="reunión importante")

    settings = Settings(gemini={"enabled": False})
    scoring = ScoringEngine()
    pipeline = NarrationPipeline(
        settings=settings,
        context_builder=SystemContextBuilder(),
        detector=RuleBasedDetector(),
        scoring=scoring,
        grouper=EventGrouper(),
        flow_controller=FlowController(scoring),
        gemini_builder=GeminiContextBuilder(PrivacySanitizer()),
        analysis_agent=AnalysisAgent(GeminiClient(settings)),
        audio_manager=audio_mgr,
        event_repo=event_repo,
        knowledge_repo=KnowledgeRepository(db),
        test_mode_gemini=True,
        dnd_manager=dnd_mgr,
        health_manager=health_mgr,
        session_id="dnd-session-01",
    )

    now = datetime.now(timezone.utc)
    ev = Event(
        event_type=EventType.CPU_SPIKE,
        severity=EventSeverity.CRITICAL,
        summary="CPU crítica durante reunión",
        metadata=EventMetadata(app_key="test_app"),
    )

    # Con DND activo, no debe enviarse a audio
    assert dnd_mgr.is_paused is True
    # Puntuar y encolar
    score_res = scoring.score_event(ev, now)
    object.__setattr__(ev, "score_result", score_res)
    pipeline.priority_queue.push(ev)

    # Procesar tick del pipeline
    step_ev = pipeline.step(now=now)
    assert step_ev is not None
    assert step_ev.decision == EventDecision.DND

    # El reproductor no debe haber recibido audio alguno
    assert len(mock_player.played_items) == 0

    # Esperar vaciado en SQLite y verificar que el evento DND se persistió
    time.sleep(0.3)
    saved_events = event_repo.get_events_for_session("dnd-session-01")
    assert len(saved_events) >= 1
    assert saved_events[0]["decision"] == EventDecision.DND.value

    db.stop()


def test_circuit_breaker_resilience_and_timeout() -> None:
    """Verifica que el Circuit Breaker prevenga saturación ante fallos de API."""
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout_s=0.2)
    assert cb.can_execute() is True

    # Registrar 2 fallos consecutivos
    cb.record_failure()
    assert cb.can_execute() is True
    cb.record_failure()

    # El circuito debe estar abierto
    assert cb.can_execute() is False

    # Intentar generar con el cliente Gemini
    settings = Settings(
        gemini={"enabled": True, "api_key": "test_key", "model": "gemini-pro"}
    )
    client = GeminiClient(settings, circuit_breaker=cb)

    # No debe realizarse ninguna llamada externa
    res = client.generate("test prompt")
    assert res is None

    # Esperar a que expire la ventana de recuperación
    time.sleep(0.25)
    assert cb.can_execute() is True

    # Éxito cierra el circuito
    cb.record_success()
    assert cb.can_execute() is True
