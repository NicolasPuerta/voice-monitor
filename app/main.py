"""Punto de entrada de Ubuntu Voice Monitor."""

import argparse
import sys
import time
from datetime import datetime, timezone

from app import __version__

STARTUP_MESSAGE: str = f"Ubuntu Voice Monitor v{__version__} se inició correctamente."


def get_startup_message() -> str:
    """Construye el mensaje de inicio de la aplicación.

    Returns:
        Mensaje indicando que la aplicación se inició correctamente.
    """
    return STARTUP_MESSAGE


def main(argv: list[str] | None = None, run_loop: bool | None = None) -> int:
    """Ejecuta la aplicación Ubuntu Voice Monitor.

    Args:
        argv: Argumentos de línea de comandos opcionales.
        run_loop: Si debe ejecutar el bucle de monitoreo continuo.
            Por defecto es True, salvo cuando se ejecuta bajo pruebas (pytest).

    Returns:
        Código de salida del proceso (0 indica éxito).
    """
    print(get_startup_message())

    if run_loop is None:
        run_loop = "pytest" not in sys.modules

    if not run_loop:
        return 0

    parser = argparse.ArgumentParser(
        prog="python -m app",
        description="Ubuntu Voice Monitor: Observa el sistema y narra eventos.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Modo demo con umbral de CPU bajo (0.1%%) para activación inmediata.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Número de iteraciones a ejecutar (por defecto: continuo hasta Ctrl+C).",
    )
    parser.add_argument(
        "--test-gemini",
        action="store_true",
        help="Simula el análisis de Gemini sin realizar llamadas externas a la API.",
    )

    args = parser.parse_args(argv)

    from app.collectors.health import SourceHealthManager
    from app.core.dnd import DNDManager
    from app.core.analysis import AnalysisAgent
    from app.core.audio.adapters.espeak import EspeakGenerator
    from app.core.audio.adapters.gemini import GeminiAudioGenerator
    from app.core.audio.adapters.piper import PiperGenerator
    from app.core.audio.manager import AudioQueueManager
    from app.core.audio.player import SystemAudioPlayer
    from app.core.config import Settings
    from app.core.context import SystemContextBuilder
    from app.core.detector import RuleBasedDetector
    from app.core.flow import EventGrouper, FlowController
    from app.core.gemini import GeminiClient, GeminiContextBuilder
    from app.core.logging import configure_logging, get_logger
    from app.core.pipeline import NarrationPipeline
    from app.core.privacy import PrivacySanitizer
    from app.core.scoring import ScoringEngine
    from app.storage.db import BackgroundDatabase
    from app.storage.repositories import EventRepository, KnowledgeRepository

    try:
        settings = Settings.load()
    except Exception as exc:
        print(f"Error cargando configuración: {exc}", file=sys.stderr)
        return 1

    configure_logging(settings.app.log_level)
    logger = get_logger("app.main")
    logger.info("Iniciando componentes del monitor...")

    # 0. Salud de fuentes y No Molestar (DND)
    health_manager = SourceHealthManager()
    dnd_manager = DNDManager(
        health_manager=health_manager,
        manual_dnd=settings.dnd.enabled,
    )

    # 1. Base de datos
    db = BackgroundDatabase(settings.storage.db_path, health_manager=health_manager)
    event_repo = EventRepository(db)
    knowledge_repo = KnowledgeRepository(db)

    # 2. Privacidad y Gemini
    sanitizer = PrivacySanitizer()
    gemini_client = GeminiClient(settings)
    analysis_agent = AnalysisAgent(gemini_client)
    gemini_builder = GeminiContextBuilder(sanitizer)

    # 3. Subsistema de Audio (Piper es el primordial)
    player = SystemAudioPlayer()

    piper_kwargs = {}
    if settings.narration.piper_model_path:
        piper_kwargs["model_path"] = settings.narration.piper_model_path
    piper = PiperGenerator(**piper_kwargs)

    # Fallbacks: espeak-ng (2º) y Gemini Audio como ÚLTIMO RECURSO
    espeak = EspeakGenerator(voice="es-la")
    gemini_audio = GeminiAudioGenerator(settings)
    fallbacks = [espeak, gemini_audio]

    audio_manager = AudioQueueManager(
        player,
        primary_generator=piper,
        fallback_generators=fallbacks,
        health_manager=health_manager,
    )

    # 4. Pipeline Core
    context_builder = SystemContextBuilder()
    cpu_threshold = 0.1 if args.demo else 80.0
    detector = RuleBasedDetector(cpu_threshold=cpu_threshold)
    scoring = ScoringEngine()
    grouper = EventGrouper(window_s=3.0)
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
        test_mode_gemini=args.test_gemini,
        dnd_manager=dnd_manager,
        health_manager=health_manager,
    )

    logger.info(
        "Monitor activo en modo %s. Umbral CPU: %.1f%%. Presiona Ctrl+C para salir.",
        "DEMO" if args.demo else "PRODUCCIÓN",
        cpu_threshold,
    )

    try:
        count = 0
        while args.iterations is None or count < args.iterations:
            now = datetime.now(timezone.utc)
            pipeline.step(now)
            time.sleep(settings.collector.interval_s if not args.demo else 1.0)
            count += 1
    except KeyboardInterrupt:
        logger.info("Interrupción recibida del usuario.")
    finally:
        logger.info("Deteniendo servicios...")
        pipeline.stop()
        audio_manager.shutdown()
        db.stop()
        logger.info("Ubuntu Voice Monitor finalizado limpiamente.")

    return 0
