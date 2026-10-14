"""Ejecución de demostración del Pipeline End-to-End."""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Asegurar path correcto
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.analysis import AnalysisAgent  # noqa: E402
from app.core.audio.adapters.espeak import EspeakGenerator  # noqa: E402
from app.core.audio.adapters.gemini import GeminiAudioGenerator  # noqa: E402
from app.core.audio.adapters.piper import PiperGenerator  # noqa: E402
from app.core.audio.manager import AudioQueueManager  # noqa: E402
from app.core.audio.player import SystemAudioPlayer  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.context import SystemContextBuilder  # noqa: E402
from app.core.detector import RuleBasedDetector  # noqa: E402
from app.core.flow import EventGrouper, FlowController  # noqa: E402
from app.core.gemini import GeminiClient, GeminiContextBuilder  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.core.pipeline import NarrationPipeline  # noqa: E402
from app.core.privacy import PrivacySanitizer  # noqa: E402
from app.core.scoring import ScoringEngine  # noqa: E402
from app.storage.db import BackgroundDatabase  # noqa: E402
from app.storage.repositories import EventRepository, KnowledgeRepository  # noqa: E402


def run_demo(iterations: int | None = None) -> None:
    """Ejecuta el monitor completo de demostración."""
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

    # 3. Audio: Piper es el PRIMORDIAL; espeak respaldo; Gemini ÚLTIMO RECURSO
    player = SystemAudioPlayer()

    piper_kwargs = {}
    if settings.narration.piper_model_path:
        piper_kwargs["model_path"] = settings.narration.piper_model_path
    piper = PiperGenerator(**piper_kwargs)

    espeak = EspeakGenerator(voice="es-la")
    gemini_audio = GeminiAudioGenerator(settings)

    # Cascada estricta: Piper (1º) -> espeak-ng (2º) -> Gemini Audio (Último recurso)
    fallbacks = [espeak, gemini_audio]
    audio_manager = AudioQueueManager(
        player,
        primary_generator=piper,
        fallback_generators=fallbacks,
    )

    # 4. Core Pipeline
    context_builder = SystemContextBuilder()
    detector = RuleBasedDetector(cpu_threshold=0.1)  # Umbral para demo inmediata
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
        test_mode_gemini=False,
    )

    logger.info("Pipeline construido con éxito.")
    logger.info(
        "Prioridad de voz: 1º Piper TTS | 2º espeak-ng | 3º Gemini Audio (último recurso)"
    )
    logger.info("Ejecutando monitoreo continuo (Pulsa Ctrl+C para salir)...")

    try:
        count = 0
        while iterations is None or count < iterations:
            now = datetime.now(timezone.utc)
            pipeline.step(now)
            time.sleep(1.0)
            count += 1
    except KeyboardInterrupt:
        logger.info("Interrupción recibida.")
    finally:
        logger.info("Apagando servicios...")
        pipeline.stop()
        audio_manager.shutdown()
        db.stop()
        logger.info("Demo finalizada.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Demo del Pipeline End-to-End.")
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Iteraciones a ejecutar (por defecto: continuo hasta Ctrl+C).",
    )
    cli_args = parser.parse_args()
    run_demo(iterations=cli_args.iterations)
