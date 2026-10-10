"""Ejecucin de demostracin del Pipeline End-to-End."""

import sys
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

# Asegurar path correcto
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.context import SystemContextBuilder
from app.core.detector import RuleBasedDetector
from app.core.scoring import ScoringEngine
from app.core.flow import EventGrouper, FlowController
from app.core.privacy import PrivacySanitizer
from app.core.gemini import GeminiContextBuilder, GeminiClient
from app.core.analysis import AnalysisAgent
from app.core.pipeline import NarrationPipeline

# Stubbd Audio y DB para la demo rpida sin dependencias
from app.storage.db import BackgroundDatabase
from app.storage.repositories import EventRepository, KnowledgeRepository
from app.core.audio.manager import AudioQueueManager
from app.core.audio.player import SystemAudioPlayer
from app.core.audio.adapters.espeak import EspeakGenerator
from app.core.audio.adapters.gemini import GeminiAudioGenerator


def run_demo() -> None:
    settings = Settings.load()
    configure_logging("INFO")

    logger = logging.getLogger("DEMO")
    logger.info("Iniciando Demo End-to-End Voice Monitor...")

    # 1. Base de datos
    db = BackgroundDatabase(Path.home() / ".local/share/ubuntu-voice-monitor/demo.db")
    event_repo = EventRepository(db)
    knowledge_repo = KnowledgeRepository(db)

    # 2. Privacidad y Gemini
    sanitizer = PrivacySanitizer()
    gemini_client = GeminiClient(settings)
    analysis_agent = AnalysisAgent(gemini_client)
    gemini_builder = GeminiContextBuilder(sanitizer)

    # 3. Audio
    player = SystemAudioPlayer()
    
    fallbacks = []
    
    # Piper si fue configurado en .env
    from app.core.audio.adapters.piper import PiperGenerator
    if settings.narration.piper_model_path:
        piper = PiperGenerator(model_path=settings.narration.piper_model_path)
        fallbacks.append(piper)
        
    espeak = EspeakGenerator(voice="es-la")
    fallbacks.append(espeak)
    
    gemini_audio = GeminiAudioGenerator(settings)
    audio_manager = AudioQueueManager(player, primary_generator=gemini_audio, fallback_generators=fallbacks)

    # 4. Core
    context_builder = SystemContextBuilder()
    detector = RuleBasedDetector(
        cpu_threshold=0.1
    )  # Umbral finsimo para asegurar deteccin en la demo
    scoring = ScoringEngine()
    grouper = EventGrouper(window_s=2.0)
    flow = FlowController(scoring)

    pipeline = NarrationPipeline(
        settings=settings,
        context_builder=context_builder,
        detector=detector,
        scoring=scoring,
        grouper=grouper,
        flow_controller=flow,
        gemini_builder=gemini_builder,
        analysis_agent=analysis_agent,
        audio_manager=audio_manager,
        event_repo=event_repo,
        knowledge_repo=knowledge_repo,
        test_mode_gemini=False,  # Usar Gemini real si hay API Key
    )

    logger.info("Pipeline construido. Ejecutando monitoreo (Pulsa Ctrl+C para salir)...")

    try:
        # Simulamos 5 segundos de ejecucin continua
        for i in range(10):
            now = datetime.now(timezone.utc)
            pipeline.step(now)
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Interrupcin recibida.")
    finally:
        logger.info("Apagando servicios...")
        pipeline.stop()
        audio_manager.shutdown()
        db.stop()
        logger.info("Demo finalizada.")


if __name__ == "__main__":
    run_demo()
