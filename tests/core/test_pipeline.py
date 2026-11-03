"""Prueba end-to-end simulada del Pipeline de Narración."""

from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
import time

from app.core.pipeline import NarrationPipeline
from app.core.dnd import DNDManager
from app.collectors.health import SourceHealthManager
from app.domain.events import Event, EventMetadata
from app.domain.enums import EventType, EventSeverity, EventDecision

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_pipeline_end_to_end() -> None:
    settings = MagicMock()
    context_builder = MagicMock()
    detector = MagicMock()
    scoring = MagicMock()
    grouper = MagicMock()
    flow = MagicMock()
    gemini_builder = MagicMock()
    analysis_agent = MagicMock()
    audio = MagicMock()
    event_repo = MagicMock()
    knowledge_repo = MagicMock()

    pipeline = NarrationPipeline(
        settings=settings,
        context_builder=context_builder,
        detector=detector,
        scoring=scoring,
        grouper=grouper,
        flow_controller=flow,
        gemini_builder=gemini_builder,
        analysis_agent=analysis_agent,
        audio_manager=audio,
        event_repo=event_repo,
        knowledge_repo=knowledge_repo,
        test_mode_gemini=True,
    )

    sys_ctx = MagicMock()
    sys_ctx.resources.load_average = (1, 1, 1)
    sys_ctx.resources.memory_percent = 50.0
    sys_ctx.apps = []
    context_builder.build.return_value = sys_ctx

    dummy_event = Event(
        event_type=EventType.CPU_SPIKE, severity=EventSeverity.HIGH, summary="Test Spike"
    )

    detector.detect.return_value = [dummy_event]
    grouper.should_flush.return_value = True
    grouper.flush.return_value = [dummy_event]
    scoring.score_event.return_value = MagicMock()

    flow.process_queue.return_value = dummy_event

    pipeline.step(NOW)

    detector.detect.assert_called_once()
    grouper.add.assert_called_once()

    time.sleep(0.1)

    event_repo.save_event.assert_called_once_with("current_session", dummy_event)
    audio.enqueue.assert_called_once()

    pipeline.stop()


def test_pipeline_dnd_active_saves_without_speaking() -> None:
    settings = MagicMock()
    context_builder = MagicMock()
    detector = MagicMock()
    scoring = MagicMock()
    grouper = MagicMock()
    flow = MagicMock()
    gemini_builder = MagicMock()
    analysis_agent = MagicMock()
    audio = MagicMock()
    event_repo = MagicMock()
    knowledge_repo = MagicMock()

    dnd_manager = DNDManager(manual_dnd=True)
    health_manager = SourceHealthManager()

    pipeline = NarrationPipeline(
        settings=settings,
        context_builder=context_builder,
        detector=detector,
        scoring=scoring,
        grouper=grouper,
        flow_controller=flow,
        gemini_builder=gemini_builder,
        analysis_agent=analysis_agent,
        audio_manager=audio,
        event_repo=event_repo,
        knowledge_repo=knowledge_repo,
        test_mode_gemini=True,
        dnd_manager=dnd_manager,
        health_manager=health_manager,
    )

    sys_ctx = MagicMock()
    sys_ctx.resources.load_average = (1, 1, 1)
    sys_ctx.resources.memory_percent = 50.0
    sys_ctx.apps = []
    context_builder.build.return_value = sys_ctx

    dummy_event = Event(
        event_type=EventType.CPU_SPIKE,
        severity=EventSeverity.MEDIUM,
        summary="Normal load",
    )

    detector.detect.return_value = [dummy_event]
    grouper.should_flush.return_value = True
    grouper.flush.return_value = [dummy_event]
    flow.process_queue.return_value = dummy_event

    pipeline.step(NOW)

    time.sleep(0.1)

    # Evento guardado con decisión DND
    assert dummy_event.decision == EventDecision.DND
    event_repo.save_event.assert_called_once_with("current_session", dummy_event)

    # No debe haberse mandado a la cola de audio
    audio.enqueue.assert_not_called()

    pipeline.stop()


def test_pipeline_gemini_failure_degrades_gracefully() -> None:
    settings = MagicMock()
    context_builder = MagicMock()
    detector = MagicMock()
    scoring = MagicMock()
    grouper = MagicMock()
    flow = MagicMock()
    gemini_builder = MagicMock()
    analysis_agent = MagicMock()
    audio = MagicMock()
    event_repo = MagicMock()
    knowledge_repo = MagicMock()

    health_manager = SourceHealthManager()

    # analysis_agent falla retornando None
    analysis_agent.analyze.return_value = None

    pipeline = NarrationPipeline(
        settings=settings,
        context_builder=context_builder,
        detector=detector,
        scoring=scoring,
        grouper=grouper,
        flow_controller=flow,
        gemini_builder=gemini_builder,
        analysis_agent=analysis_agent,
        audio_manager=audio,
        event_repo=event_repo,
        knowledge_repo=knowledge_repo,
        test_mode_gemini=False,
        health_manager=health_manager,
    )

    sys_ctx = MagicMock()
    sys_ctx.resources.load_average = (1, 1, 1)
    sys_ctx.resources.memory_percent = 50.0
    sys_ctx.apps = []
    context_builder.build.return_value = sys_ctx

    dummy_event = Event(
        event_type=EventType.CPU_SPIKE, severity=EventSeverity.HIGH, summary="Spike"
    )

    detector.detect.return_value = [dummy_event]
    grouper.should_flush.return_value = True
    grouper.flush.return_value = [dummy_event]
    flow.process_queue.return_value = dummy_event

    pipeline.step(NOW)

    time.sleep(0.1)

    # El fallo de Gemini se registra en health_manager sin detener el sistema
    assert health_manager.get_consecutive_failures("gemini") == 1
    # Y el evento se guardó en BD antes del intento de Gemini
    event_repo.save_event.assert_called_once_with("current_session", dummy_event)

    pipeline.stop()


def _build_pipeline_for_worker(
    settings: MagicMock, analysis_agent: MagicMock, audio: MagicMock
) -> tuple[NarrationPipeline, MagicMock, MagicMock, MagicMock, MagicMock]:
    context_builder = MagicMock()
    detector = MagicMock()
    grouper = MagicMock()
    flow = MagicMock()
    knowledge_repo = MagicMock()
    knowledge_repo.get_knowledge.return_value.short_text = "Proceso de prueba"

    pipeline = NarrationPipeline(
        settings=settings,
        context_builder=context_builder,
        detector=detector,
        scoring=MagicMock(),
        grouper=grouper,
        flow_controller=flow,
        gemini_builder=MagicMock(),
        analysis_agent=analysis_agent,
        audio_manager=audio,
        event_repo=MagicMock(),
        knowledge_repo=knowledge_repo,
        test_mode_gemini=False,
        health_manager=SourceHealthManager(),
    )

    sys_ctx = MagicMock()
    sys_ctx.resources.load_average = (1, 1, 1)
    sys_ctx.resources.memory_percent = 50.0
    sys_ctx.apps = []
    context_builder.build.return_value = sys_ctx
    return pipeline, context_builder, detector, grouper, flow


def _step_with_event(
    pipeline: NarrationPipeline,
    detector: MagicMock,
    grouper: MagicMock,
    flow: MagicMock,
    event: Event,
) -> None:
    detector.detect.return_value = [event]
    grouper.should_flush.return_value = True
    grouper.flush.return_value = [event]
    flow.process_queue.return_value = event
    pipeline.step(NOW)
    time.sleep(0.1)


def test_pipeline_gemini_disabled_narrates_locally() -> None:
    settings = MagicMock()
    settings.gemini.enabled = False
    analysis_agent = MagicMock()
    audio = MagicMock()
    pipeline, _, detector, grouper, flow = _build_pipeline_for_worker(
        settings, analysis_agent, audio
    )
    event = Event(
        event_type=EventType.CPU_SPIKE,
        severity=EventSeverity.HIGH,
        summary="Alta CPU en firefox",
        metadata=EventMetadata(app_key="exe:/usr/bin/firefox"),
    )

    _step_with_event(pipeline, detector, grouper, flow, event)

    analysis_agent.analyze.assert_not_called()
    audio.enqueue.assert_called_once_with("Alta CPU en firefox. Proceso de prueba.")
    assert pipeline.health_manager is not None
    assert pipeline.health_manager.get_consecutive_failures("gemini") == 0
    pipeline.stop()


def test_pipeline_gemini_failure_falls_back_to_local_speech() -> None:
    analysis_agent = MagicMock()
    analysis_agent.analyze.return_value = None
    audio = MagicMock()
    pipeline, _, detector, grouper, flow = _build_pipeline_for_worker(
        MagicMock(), analysis_agent, audio
    )
    event = Event(
        event_type=EventType.CPU_SPIKE, severity=EventSeverity.HIGH, summary="Spike"
    )

    _step_with_event(pipeline, detector, grouper, flow, event)

    audio.enqueue.assert_called_once_with("Spike.")
    pipeline.stop()


def test_pipeline_queue_uses_configured_event_ttl() -> None:
    settings = MagicMock()
    settings.narration.event_ttl_s = 45.0
    pipeline, *_ = _build_pipeline_for_worker(settings, MagicMock(), MagicMock())

    assert pipeline.priority_queue.ttl_s == 45.0
    pipeline.stop()


def test_pipeline_adds_risk_engine_events_to_detection() -> None:
    """Las señales del RiskEngine entran al pipeline como eventos detectados."""
    pipeline, _, detector, grouper, flow = _build_pipeline_for_worker(
        MagicMock(), MagicMock(), MagicMock()
    )
    risk_event = Event(
        event_type=EventType.SERVICE_FAILED,
        severity=EventSeverity.HIGH,
        summary="El servicio 'web.service' falló",
    )
    signal = MagicMock()
    pipeline.risk_engine = MagicMock()
    pipeline.risk_engine.evaluate.return_value = [signal]
    detector.detect.return_value = []
    grouper.should_flush.return_value = False
    flow.process_queue.return_value = None

    with patch(
        "app.core.pipeline.RiskEngine.signals_to_events", return_value=[risk_event]
    ):
        pipeline.step(NOW)

    grouper.add.assert_called_once_with(risk_event, NOW)
    pipeline.stop()
