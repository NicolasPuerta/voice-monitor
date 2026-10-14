"""Pruebas del motor de reproducción (ReplayEngine) sobre diversos escenarios."""

from pathlib import Path
from unittest.mock import MagicMock

from app.collectors.health import SourceHealthManager
from app.core.analysis import AnalysisAgent
from app.core.audio.manager import AudioQueueManager
from app.core.config import AppSettings, GeminiSettings, Settings
from app.core.context import SystemContextBuilder
from app.core.detector import RuleBasedDetector
from app.core.dnd import DNDManager
from app.core.flow import EventGrouper, FlowController
from app.core.gemini import GeminiContextBuilder
from app.core.metrics import PerformanceMetrics
from app.core.pipeline import NarrationPipeline
from app.core.privacy import PrivacySanitizer
from app.core.replay import ReplayEngine
from app.core.scoring import ScoringEngine
from app.domain.enums import EventDecision, EventType
from app.storage.db import BackgroundDatabase
from app.storage.repositories import EventRepository, KnowledgeRepository
from tests.fixtures.scenarios import (
    BASE_TIME,
    create_cpu_spike_scenario,
    create_docker_scenario,
    create_firefox_scenario,
    create_idle_scenario,
    create_memory_pressure_scenario,
    create_process_failures_scenario,
)


def _make_test_pipeline(
    tmp_path: Path,
    test_mode_gemini: bool = True,
    dnd_manager: DNDManager | None = None,
    metrics: PerformanceMetrics | None = None,
) -> tuple[NarrationPipeline, BackgroundDatabase]:
    """Crea una tubería completamente aislada y sin llamadas de red para tests."""
    settings = Settings(
        app=AppSettings(),
        gemini=GeminiSettings(enabled=False),
    )
    health = SourceHealthManager()
    db = BackgroundDatabase(
        tmp_path / "test_replay.db", batch_size=5, flush_interval_s=0.1
    )
    event_repo = EventRepository(db)
    knowledge_repo = KnowledgeRepository(db)

    sanitizer = PrivacySanitizer()
    mock_gemini = MagicMock()
    mock_gemini.generate.return_value = '{"summary": "ok", "speech_text": "alerta"}'
    analysis_agent = AnalysisAgent(mock_gemini)
    gemini_builder = GeminiContextBuilder(sanitizer)

    mock_player = MagicMock()
    mock_gen = MagicMock()
    mock_gen.name = "mock_piper"
    mock_gen.generate.return_value = MagicMock()
    audio_mgr = AudioQueueManager(
        player=mock_player,
        primary_generator=mock_gen,
        health_manager=health,
        metrics=metrics,
    )

    pipeline = NarrationPipeline(
        settings=settings,
        context_builder=SystemContextBuilder(),
        detector=RuleBasedDetector(),
        scoring=ScoringEngine(),
        grouper=EventGrouper(window_s=1.0),
        flow_controller=FlowController(ScoringEngine()),
        gemini_builder=gemini_builder,
        analysis_agent=analysis_agent,
        audio_manager=audio_mgr,
        event_repo=event_repo,
        knowledge_repo=knowledge_repo,
        test_mode_gemini=test_mode_gemini,
        dnd_manager=dnd_manager,
        health_manager=health,
        metrics=metrics,
    )
    return pipeline, db


def test_replay_idle_scenario(tmp_path: Path) -> None:
    """Verifica que el escenario idle no genere spam ni alertas excesivas."""
    pipeline, db = _make_test_pipeline(tmp_path)
    metrics = PerformanceMetrics()
    engine = ReplayEngine(pipeline, metrics=metrics)

    ticks = create_idle_scenario(BASE_TIME, ticks=5)
    result = engine.run(ticks)

    assert result.total_ticks == 5
    # En reposo ningún evento crítico debe sonar
    assert len(result.spoken_events) == 0
    assert result.metrics_summary["resources"]["sample_count"] >= 5

    pipeline.shutdown()
    db.stop()


def test_replay_cpu_spike_scenario(tmp_path: Path) -> None:
    """Verifica que un pico sostenido de CPU sea detectado y reproducido."""
    pipeline, db = _make_test_pipeline(tmp_path)
    metrics = PerformanceMetrics()
    engine = ReplayEngine(pipeline, metrics=metrics)

    ticks = create_cpu_spike_scenario(BASE_TIME, ticks=5)
    result = engine.run(ticks)

    assert result.total_ticks == 5
    assert len(result.spoken_events) >= 1
    spoken = result.spoken_events[0]
    assert spoken.decision == EventDecision.SPOKEN
    assert spoken.event_type in (
        EventType.CPU_SPIKE,
        EventType.CPU_SUSTAINED_HIGH,
        EventType.SYSTEM_PRESSURE,
    )

    pipeline.shutdown()
    db.stop()


def test_replay_memory_pressure_scenario(tmp_path: Path) -> None:
    """Verifica la detección y manejo de presión de memoria y PSI."""
    pipeline, db = _make_test_pipeline(tmp_path)
    metrics = PerformanceMetrics()
    engine = ReplayEngine(pipeline, metrics=metrics)

    ticks = create_memory_pressure_scenario(BASE_TIME, ticks=5)
    result = engine.run(ticks)

    assert result.total_ticks == 5
    # Debe haber eventos de memoria o presión detectados
    assert result.events_detected > 0

    pipeline.shutdown()
    db.stop()


def test_replay_firefox_grouping_scenario(tmp_path: Path) -> None:
    """Verifica que 10 procesos Web Content de Firefox se agrupen en 1 app."""
    pipeline, db = _make_test_pipeline(tmp_path)
    ticks = create_firefox_scenario(BASE_TIME, children_count=10, ticks=3)

    # Revisar contexto del primer tick
    ctx = ticks[0].context
    firefox_apps = [a for a in ctx.apps if a.name == "firefox"]
    assert len(firefox_apps) == 1

    group = firefox_apps[0]
    # El padre + 10 hijos = 11 procesos en total en el grupo
    assert len(group.processes) == 11
    # La CPU y RAM deben estar sumadas y no separadas
    assert group.cpu_percent > 50.0

    engine = ReplayEngine(pipeline)
    result = engine.run(ticks)
    assert result.total_ticks == 3

    pipeline.shutdown()
    db.stop()


def test_replay_docker_grouping_scenario(tmp_path: Path) -> None:
    """Verifica que los procesos de contenedores Docker se agrupen por cgroup."""
    pipeline, db = _make_test_pipeline(tmp_path)
    ticks = create_docker_scenario(BASE_TIME, ticks=3)

    ctx = ticks[0].context
    docker_apps = [a for a in ctx.apps if "docker" in a.app_key]
    assert len(docker_apps) == 1
    assert len(docker_apps[0].processes) == 2

    engine = ReplayEngine(pipeline)
    result = engine.run(ticks)
    assert result.total_ticks == 3

    pipeline.shutdown()
    db.stop()


def test_replay_process_failures_scenario(tmp_path: Path) -> None:
    """Verifica que la salida o caída abrupta de un proceso no rompa el monitor."""
    pipeline, db = _make_test_pipeline(tmp_path)
    ticks = create_process_failures_scenario(BASE_TIME, ticks=4)

    engine = ReplayEngine(pipeline)
    result = engine.run(ticks)

    assert result.total_ticks == 4
    # En el tick 0 el proceso 5001 corre intensamente
    assert ticks[0].context.apps[0].processes[0].pid == 5001
    # En el tick 3 el proceso ya no existe en el contexto
    pids_final = [
        p.pid for app in ticks[3].context.apps for p in app.processes
    ]
    assert 5001 not in pids_final

    pipeline.shutdown()
    db.stop()
