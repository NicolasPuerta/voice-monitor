"""Pipeline principal de monitoreo, análisis y narración."""

import logging
import queue
import threading
from datetime import datetime
from typing import Any

from app.collectors.health import SourceHealthManager
from app.core.analysis import AnalysisAgent
from app.core.audio.manager import AudioQueueManager
from app.core.config import Settings
from app.core.context import SystemContextBuilder
from app.core.detector import RuleBasedDetector
from app.core.dnd import DNDManager
from app.core.flow import EventGrouper, FlowController, PriorityQueue
from app.core.gemini import GeminiContextBuilder
from app.core.scoring import ScoringEngine
from app.domain.enums import EventDecision
from app.domain.events import Event
from app.storage import EventRepository, KnowledgeRepository

logger = logging.getLogger(__name__)


class NarrationPipeline:
    """Orquesta el ciclo End-to-End con soporte DND y degradación elegante."""

    def __init__(
        self,
        settings: Settings,
        context_builder: SystemContextBuilder,
        detector: RuleBasedDetector,
        scoring: ScoringEngine,
        grouper: EventGrouper,
        flow_controller: FlowController,
        gemini_builder: GeminiContextBuilder,
        analysis_agent: AnalysisAgent,
        audio_manager: AudioQueueManager | None,
        event_repo: EventRepository | None,
        knowledge_repo: KnowledgeRepository | None,
        test_mode_gemini: bool = False,
        dnd_manager: DNDManager | None = None,
        health_manager: SourceHealthManager | None = None,
        metrics: Any | None = None,
        session_id: str | None = None,
        session_repo: Any | None = None,
    ):
        self.settings = settings
        self.context_builder = context_builder
        self.detector = detector
        self.scoring = scoring
        self.grouper = grouper
        self.flow = flow_controller
        self.gemini_builder = gemini_builder
        self.analysis_agent = analysis_agent
        self.audio = audio_manager
        self.event_repo = event_repo
        self.knowledge_repo = knowledge_repo
        self.test_mode_gemini = test_mode_gemini

        self.dnd_manager = dnd_manager
        self.health_manager = health_manager
        self.metrics = metrics
        self.session_id = session_id or "current_session"
        self.session_repo = session_repo

        if self.session_repo and self.session_id:
            from datetime import timezone
            self.session_repo.start_session(
                self.session_id, datetime.now(timezone.utc)
            )

        self.priority_queue = PriorityQueue(ttl_s=30.0)

        # Worker de Gemini: (event, knowledge, load_avg, mem_pct, skip_audio)
        self._gemini_queue: queue.Queue[
            tuple[Event, str | None, tuple[float, float, float], float, bool] | None
        ] = queue.Queue()
        self._stop_event = threading.Event()
        self._gemini_thread = threading.Thread(target=self._gemini_worker, daemon=True)
        self._gemini_thread.start()

    def step(
        self,
        now: datetime,
        context: Any | None = None,
        metrics: Any | None = None,
    ) -> Event | None:
        """Ejecuta un tick del loop principal sin bloquear."""
        eff_metrics = metrics or self.metrics

        # 1. Obtener contexto del SO (o usar el contexto inyectado)
        if context is not None:
            ctx = context
        else:
            if eff_metrics is not None:
                with eff_metrics.measure_collector("system_and_processes"):
                    ctx = self.context_builder.build()
            else:
                ctx = self.context_builder.build()

        # 2. Detección
        new_events = self.detector.detect(ctx, now)
        if eff_metrics is not None:
            eff_metrics.increment_counter("events_detected", len(new_events))
        for ev in new_events:
            self.grouper.add(ev, now)

        # 3. Flushear coalescencia y puntuar
        if self.grouper.should_flush(now):
            coalesced = self.grouper.flush()
            for ev in coalesced:
                if eff_metrics is not None:
                    with eff_metrics.measure_scoring():
                        score_res = self.scoring.score_event(ev, now)
                    eff_metrics.increment_counter("events_scored", 1)
                else:
                    score_res = self.scoring.score_event(ev, now)

                ev.score_result = score_res  # type: ignore[misc]
                # Eventos con score numérico muy bajo (< 10.0) se omiten por umbral
                score_val = getattr(score_res, "score", None)
                if isinstance(score_val, (int, float)) and score_val < 10.0:
                    ev.decision = EventDecision.THRESHOLD_OMITTED  # type: ignore[misc]
                    if eff_metrics is not None:
                        eff_metrics.record_decision(EventDecision.THRESHOLD_OMITTED)
                    if self.event_repo:
                        self.event_repo.save_event(self.session_id, ev)
                else:
                    self.priority_queue.push(ev)

        # 4. Control de Flujo (Preemption, Token Bucket)
        event_to_speak = self.flow.process_queue(self.priority_queue, now)

        if event_to_speak:
            if eff_metrics is not None:
                eff_metrics.record_event_latency(event_to_speak, now)

            # Comprobación de DND (No Molestar)
            process_names = (
                [getattr(a, "display_name", getattr(a, "name", "")) for a in ctx.apps]
                if ctx.apps
                else []
            )
            is_suppressed = False
            if self.dnd_manager:
                is_suppressed = self.dnd_manager.handle_event_dnd(
                    event_to_speak, process_names, now
                )

            if is_suppressed:
                if eff_metrics is not None:
                    eff_metrics.record_decision(EventDecision.DND)
                # Guardar en SQLite como DND / DEFERRED sin perderlo
                if self.event_repo:
                    self.event_repo.save_event(self.session_id, event_to_speak)

                # Si es modo texto, se analiza con Gemini pero no se encola audio
                if self.dnd_manager and self.dnd_manager.text_only:
                    self._dispatch_to_gemini(
                        event_to_speak,
                        ctx.resources.load_average,
                        ctx.resources.memory_percent,
                        skip_audio=True,
                    )
            else:
                if eff_metrics is not None:
                    eff_metrics.record_decision(EventDecision.SPOKEN)
                self._dispatch_to_gemini(
                    event_to_speak,
                    ctx.resources.load_average,
                    ctx.resources.memory_percent,
                    skip_audio=False,
                )

        return event_to_speak

    def _dispatch_to_gemini(
        self,
        event: Event,
        load_avg: tuple[float, float, float] | None,
        mem_pct: float | None,
        skip_audio: bool = False,
    ) -> None:
        """Envía el evento al worker asíncrono guardándolo primero en BD."""
        if self.event_repo:
            self.event_repo.save_event(self.session_id, event)

        knowledge = None
        if self.knowledge_repo and event.metadata.app_key:
            k = self.knowledge_repo.get_knowledge(
                event.metadata.app_key, event.metadata.app_name or ""
            )
            knowledge = k.short_text

        self._gemini_queue.put(
            (event, knowledge, load_avg or (0, 0, 0), mem_pct or 0.0, skip_audio)
        )

    def _gemini_worker(self) -> None:
        """Hilo dedicado a comunicarse con Gemini protegiendo los collectors."""
        while not self._stop_event.is_set():
            try:
                item = self._gemini_queue.get(timeout=1.0)
                if item is None:
                    break

                event, knowledge, load_avg, mem_pct, skip_audio = item

                # Degradación elegante: revisar circuit breaker de Gemini
                if self.health_manager and not self.health_manager.can_attempt("gemini"):
                    logger.debug("Omitiendo Gemini por backoff/circuit breaker.")
                    self._gemini_queue.task_done()
                    continue

                if self.test_mode_gemini:
                    speech = f"Modo prueba: evento {event.summary}."
                    logger.info("[TEST GEMINI] Analizado: %s", speech)
                    if not skip_audio and self.audio:
                        self.audio.enqueue(speech)
                    self._gemini_queue.task_done()
                    continue

                from app.domain.context import SystemContext
                from app.domain.snapshots import ResourceSnapshot

                dummy_ctx = SystemContext(
                    collected_at=event.detected_at,
                    resources=ResourceSnapshot(
                        cpu_percent=0.0,
                        cpu_count_logical=1,
                        load_average=load_avg,
                        memory_total_bytes=1000,
                        memory_used_bytes=500,
                        memory_available_bytes=500,
                        memory_percent=mem_pct or 0.0,
                    ),
                )

                gemini_ctx = self.gemini_builder.build(event, dummy_ctx, knowledge)

                if self.metrics:
                    with self.metrics.measure_gemini():
                        result = self.analysis_agent.analyze(gemini_ctx)
                else:
                    result = self.analysis_agent.analyze(gemini_ctx)

                if result:
                    if self.health_manager:
                        self.health_manager.record_success("gemini")
                    logger.info("[GEMINI SUCCESS] %s", result.speech_text)
                    if not skip_audio and self.audio:
                        self.audio.enqueue(result.speech_text)
                else:
                    if self.health_manager:
                        self.health_manager.record_failure(
                            "gemini", reason="Respuesta de análisis nula"
                        )
                    logger.warning(
                        "[GEMINI FALLO] Retornó None. Monitoreo prosigue normalmente."
                    )

                self._gemini_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                if self.health_manager:
                    self.health_manager.record_failure("gemini", reason=str(e))
                logger.error("Error en worker de Gemini: %s", e)

    def stop(self) -> None:
        """Detiene limpiamente el worker del pipeline."""
        if self.session_repo and self.session_id:
            from datetime import timezone
            self.session_repo.end_session(
                self.session_id, datetime.now(timezone.utc)
            )
        self._stop_event.set()
        self._gemini_queue.put(None)
        self._gemini_thread.join(timeout=3.0)

    def shutdown(self) -> None:
        """Alias de compatibilidad para stop()."""
        self.stop()
