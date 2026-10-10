"""Pipeline principal de monitoreo, anlisis y narracin."""

import queue
import logging
import threading
from datetime import datetime

from app.core.config import Settings
from app.core.context import SystemContextBuilder
from app.core.detector import RuleBasedDetector
from app.core.scoring import ScoringEngine
from app.core.flow import EventGrouper, PriorityQueue, FlowController
from app.core.gemini import GeminiContextBuilder
from app.core.analysis import AnalysisAgent
from app.core.audio.manager import AudioQueueManager
from app.storage import EventRepository, KnowledgeRepository
from app.domain.events import Event

logger = logging.getLogger(__name__)


class NarrationPipeline:
    """Orquesta el ciclo End-to-End: Deteccin -> Scoring -> Gemini -> Audio."""

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

        self.priority_queue = PriorityQueue(ttl_s=30.0)

        # Worker de Gemini
        self._gemini_queue: queue.Queue[
            tuple[Event, str | None, tuple[float, float, float], float] | None
        ] = queue.Queue()
        self._stop_event = threading.Event()
        self._gemini_thread = threading.Thread(target=self._gemini_worker, daemon=True)
        self._gemini_thread.start()

    def step(self, now: datetime) -> None:
        """Ejecuta un paso (tick) del loop principal. No debe bloquear."""

        # 1. Obtener contexto del SO (Los collectors deben haber actualizado sus datos o se leen on-demand en el builder)
        # Asumimos que los collectors han sido cacheados o son rpidos
        ctx = self.context_builder.build()

        # 2. Deteccin
        new_events = self.detector.detect(ctx, now)
        for ev in new_events:
            self.grouper.add(ev, now)

        # 3. Flushear coalescencia y puntuar
        if self.grouper.should_flush(now):
            coalesced = self.grouper.flush()
            for ev in coalesced:
                ev.score_result = self.scoring.score_event(ev, now)
                self.priority_queue.push(ev)

        # 4. Control de Flujo (Preemption, Token Bucket)
        # Extrae un evento si es prudente narrarlo
        event_to_speak = self.flow.process_queue(self.priority_queue, now)

        if event_to_speak:
            # En FlowController se le asign SPOKEN.
            self._dispatch_to_gemini(
                event_to_speak, ctx.resources.load_average, ctx.resources.memory_percent
            )

        # Vaciar caducados a la BD
        # Para que los expirados se guarden, PriorityQueue no expone fcilmente los que tira,
        # pero para efectos del demo nos basta con guardar el event_to_speak. En produccin real
        # se pasara la lista de expirados al EventRepository.

    def _dispatch_to_gemini(
        self,
        event: Event,
        load_avg: tuple[float, float, float] | None,
        mem_pct: float | None,
    ) -> None:
        """Enva de forma asncrona a Gemini, guardando en BD primero."""

        # Guardar decisin antes de llamar a Gemini
        if self.event_repo:
            self.event_repo.save_event("current_session", event)

        # Extraer conocimiento para el context
        knowledge = None
        if self.knowledge_repo and event.metadata.app_key:
            k = self.knowledge_repo.get_knowledge(
                event.metadata.app_key, event.metadata.app_name or ""
            )
            knowledge = k.short_text

        # Enviar al worker
        self._gemini_queue.put((event, knowledge, load_avg or (0, 0, 0), mem_pct or 0.0))

    def _gemini_worker(self) -> None:
        """Hilo dedicado a comunicarse con Gemini para no trabar los collectors."""
        while not self._stop_event.is_set():
            try:
                item = self._gemini_queue.get(timeout=1.0)
                if item is None:
                    break

                event, knowledge, load_avg, mem_pct = item

                # Mock mode
                if self.test_mode_gemini:
                    speech = f"Modo prueba: evento {event.summary}."
                    logger.info(f"[TEST GEMINI] Analizado: {speech}")
                    if self.audio:
                        self.audio.enqueue(speech)
                    self._gemini_queue.task_done()
                    continue

                # Reconstruir un sub-contexto simple (GeminiContextBuilder lo hace ms formal en prod)
                # aqu inyectamos valores pasados
                from app.domain.snapshots import ResourceSnapshot
                from app.domain.context import SystemContext

                dummy_ctx = SystemContext(
                    collected_at=event.detected_at,
                    resources=ResourceSnapshot(
                        load_average=load_avg, memory_percent=mem_pct
                    ),
                )

                gemini_ctx = self.gemini_builder.build(event, dummy_ctx, knowledge)

                logger.debug("Llamando a Gemini Analysis Agent...")
                result = self.analysis_agent.analyze(gemini_ctx)

                if result:
                    logger.info(f"[GEMINI SUCCESS] {result.speech_text}")
                    if self.audio:
                        self.audio.enqueue(result.speech_text)
                else:
                    logger.warning(
                        "[GEMINI FALLO] Retorn None o invlido. Se prosigue monitoreo."
                    )

                self._gemini_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error fatal en Gemini worker: {e}")

    def stop(self) -> None:
        self._stop_event.set()
        self._gemini_queue.put(None)
        self._gemini_thread.join(timeout=3.0)
