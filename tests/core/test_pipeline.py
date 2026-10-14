"""Prueba end-to-end simulada del Pipeline de Narración."""

from unittest.mock import MagicMock
from datetime import datetime, timezone
import time

from app.core.pipeline import NarrationPipeline
from app.core.dnd import DNDManager
from app.collectors.health import SourceHealthManager
from app.domain.events import Event
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
