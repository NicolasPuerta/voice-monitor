"""Interfaz de línea de comandos (CLI) principal: comando `narrator` (MR 15).

Permite iniciar, detener, consultar el estado, pausar, reanudar y generar reportes
de sesión del Ubuntu Voice Monitor.
"""

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Sequence

from app.collectors.health import SourceHealthManager
from app.core.analysis import AnalysisAgent
from app.core.audio.adapters.espeak import EspeakGenerator
from app.core.audio.adapters.gemini import GeminiAudioGenerator
from app.core.audio.adapters.piper import PiperGenerator
from app.core.audio.manager import AudioQueueManager
from app.core.audio.player import SystemAudioPlayer
from app.core.config import Settings
from app.core.context import SystemContextBuilder
from app.core.detector import RuleBasedDetector
from app.core.dnd import DNDManager
from app.core.flow import EventGrouper, FlowController
from app.core.gemini import GeminiClient, GeminiContextBuilder
from app.core.logging import configure_logging, get_logger
from app.core.pipeline import NarrationPipeline
from app.core.platform import PlatformDetector
from app.core.privacy import PrivacySanitizer
from app.core.reports import ReportService
from app.core.runtime import RuntimeManager
from app.core.scoring import ScoringEngine
from app.storage.db import BackgroundDatabase
from app.storage.repositories import (
    EventRepository,
    KnowledgeRepository,
    SessionRepository,
    SourceHealthRepository,
)

logger = logging.getLogger("app.cli")


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos para el comando `narrator`."""
    parser = argparse.ArgumentParser(
        prog="narrator",
        description=(
            "Ubuntu Voice Monitor: Observación del sistema y narración inteligente."
        ),
    )

    # Opciones globales requeridas por el MR 15
    parser.add_argument(
        "--verbosity",
        choices=["minimal", "normal", "verbose"],
        default=None,
        help="Nivel de detalle de las narraciones y logs.",
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        default=False,
        help="Ejecuta el monitor sin emitir sonido por parlantes (modo texto/silencio).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Activa el registro detallado en modo DEBUG.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Ruta a archivo .env o configuración personalizada.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcomando: start
    start_p = subparsers.add_parser("start", help="Inicia el monitor.")
    start_p.add_argument(
        "--foreground",
        "-f",
        action="store_true",
        default=False,
        help="Ejecuta en primer plano en lugar de segundo plano.",
    )
    start_p.add_argument(
        "--demo",
        action="store_true",
        default=False,
        help="Modo demo con umbral bajo de activación (0.1%% CPU).",
    )
    start_p.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Número máximo de ticks a ejecutar.",
    )
    start_p.add_argument(
        "--test-gemini",
        action="store_true",
        default=False,
        help="Modo prueba: simula respuesta de Gemini sin conexión de red.",
    )
    start_p.add_argument(
        "--no-audio",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Ejecuta el monitor sin emitir sonido por parlantes.",
    )
    start_p.add_argument(
        "--verbosity",
        choices=["minimal", "normal", "verbose"],
        default=argparse.SUPPRESS,
        help="Nivel de detalle de las narraciones.",
    )
    start_p.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Activa el registro en modo DEBUG.",
    )
    start_p.add_argument(
        "--config",
        type=str,
        default=argparse.SUPPRESS,
        help="Ruta a archivo .env o configuración personalizada.",
    )

    # Subcomando: stop
    subparsers.add_parser("stop", help="Detiene el monitor en ejecución.")

    # Subcomando: status
    status_p = subparsers.add_parser(
        "status",
        help="Muestra el estado de collectors, Gemini, audio, sesión y DND.",
    )
    status_p.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Imprime el estado en formato JSON.",
    )

    # Subcomando: pause
    pause_p = subparsers.add_parser(
        "pause",
        help="Pausa la narración de audio (activa DND manual).",
    )
    pause_p.add_argument(
        "--reason",
        type=str,
        default="manual_cli",
        help="Motivo de la pausa.",
    )

    # Subcomando: resume
    subparsers.add_parser(
        "resume",
        help="Reanuda la narración de audio (desactiva DND).",
    )

    # Subcomando: session
    session_p = subparsers.add_parser(
        "session",
        help="Muestra información de la sesión actual o anteriores.",
    )
    session_p.add_argument(
        "--id",
        type=str,
        default=None,
        help="ID de la sesión a inspeccionar.",
    )
    session_p.add_argument(
        "--list",
        action="store_true",
        default=False,
        help="Lista las sesiones más recientes.",
    )

    # Subcomando: report
    report_p = subparsers.add_parser(
        "report",
        help="Genera un informe HTML o PDF de una sesión.",
    )
    report_p.add_argument(
        "--session",
        type=str,
        default=None,
        help="ID de la sesión a reportar (por defecto la más reciente).",
    )
    report_p.add_argument(
        "--format",
        choices=["html", "pdf", "all"],
        default="html",
        help="Formato del informe generado (html, pdf, all).",
    )
    report_p.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Ruta de salida del archivo generado.",
    )

    # Subcomando: service (MR 17)
    service_p = subparsers.add_parser(
        "service",
        help="Gestiona el servicio systemd de usuario (status, install, uninstall).",
    )
    service_p.add_argument(
        "action",
        choices=["status", "install", "uninstall", "start", "stop", "restart"],
        nargs="?",
        default="status",
        help="Acción a realizar sobre el servicio systemd de usuario.",
    )
    service_p.add_argument(
        "--unit-path",
        type=str,
        default=None,
        help="Ruta personalizada para el archivo de unidad systemd.",
    )

    return parser


def load_settings_safely(config_path: str | None) -> Settings:
    """Carga la configuración permitiendo rutas personalizadas."""
    if config_path:
        return Settings.load(env_file=Path(config_path))
    return Settings.load()


def cmd_start(args: argparse.Namespace, runtime: RuntimeManager) -> int:
    """Ejecuta el subcomando `start` en segundo plano o foreground."""
    pid = runtime.get_running_pid()
    if pid is not None:
        print(f"Ubuntu Voice Monitor ya está en ejecución (PID: {pid}).")
        return 0

    if not args.foreground:
        # Iniciar en segundo plano invocando con --foreground
        cmd = [sys.executable, "-m", "app.cli"]
        if args.verbosity:
            cmd.extend(["--verbosity", args.verbosity])
        if args.no_audio:
            cmd.append("--no-audio")
        if args.debug:
            cmd.append("--debug")
        if args.config:
            cmd.extend(["--config", args.config])
        cmd.extend(["start", "--foreground"])
        if args.demo:
            cmd.append("--demo")
        if args.test_gemini:
            cmd.append("--test-gemini")
        if args.iterations:
            cmd.extend(["--iterations", str(args.iterations)])

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True if sys.platform != "win32" else False,
        )

        # Esperar hasta 2 segundos para confirmar que registró su PID
        deadline = time.time() + 2.0
        while time.time() < deadline:
            active_pid = runtime.get_running_pid()
            if active_pid is not None:
                print(
                    f"Ubuntu Voice Monitor iniciado en segundo plano (PID: {active_pid})."
                )
                return 0
            time.sleep(0.1)

        print(
            f"Ubuntu Voice Monitor lanzado (PID tentativo: {proc.pid}). "
            "Verifique con 'narrator status'."
        )
        return 0

    # Modo foreground (bucle de monitoreo activo)
    runtime.write_pid(sys.platform and sys.platform.startswith("win") and proc_pid() or 0)
    import os

    current_pid = os.getpid()
    runtime.write_pid(current_pid)

    settings = load_settings_safely(args.config)
    log_level = "DEBUG" if args.debug else (args.verbosity or settings.app.log_level)
    configure_logging(log_level)
    app_logger = get_logger("app.cli.monitor")

    app_logger.info("Iniciando Ubuntu Voice Monitor (PID: %d)...", current_pid)

    # 1. Gestores de salud y DND
    health_manager = SourceHealthManager()
    dnd_manager = DNDManager(
        health_manager=health_manager,
        manual_dnd=settings.dnd.enabled,
        text_only=args.no_audio,
    )

    # 2. Base de datos y repositorios
    db = BackgroundDatabase(settings.storage.db_path, health_manager=health_manager)
    session_repo = SessionRepository(db)
    event_repo = EventRepository(db)
    knowledge_repo = KnowledgeRepository(db)
    SourceHealthRepository(db)

    # 3. Sesión
    session_id = f"session_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    # 4. Privacidad y Gemini
    sanitizer = PrivacySanitizer()
    gemini_client = GeminiClient(settings)
    analysis_agent = AnalysisAgent(gemini_client)
    gemini_builder = GeminiContextBuilder(sanitizer)

    # 5. Audio
    player = SystemAudioPlayer()
    piper_kwargs = {}
    if settings.narration.piper_model_path:
        piper_kwargs["model_path"] = settings.narration.piper_model_path
    piper = PiperGenerator(**piper_kwargs)
    espeak = EspeakGenerator(voice="es-la")
    gemini_audio = GeminiAudioGenerator(settings)
    fallbacks = [espeak, gemini_audio]

    audio_manager = AudioQueueManager(
        player,
        primary_generator=piper,
        fallback_generators=fallbacks,
        health_manager=health_manager,
    )

    # 6. Pipeline
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
        session_id=session_id,
        session_repo=session_repo,
    )

    app_logger.info("Monitor iniciado con éxito. Sesión: %s", session_id)

    step_interval = 1.0 if args.demo else settings.collector.interval_s
    count = 0

    try:
        while args.iterations is None or count < args.iterations:
            # Revisar comandos de control pendientes (pause, resume, stop)
            ctrl = runtime.consume_command()
            if ctrl:
                cmd_name = ctrl.get("command")
                if cmd_name == "stop":
                    app_logger.info("Comando de parada recibido desde el CLI.")
                    break
                elif cmd_name == "pause":
                    reason = ctrl.get("reason", "manual_cli")
                    dnd_manager.pause(reason)
                    app_logger.info("DND activado por comando de control: %s", reason)
                elif cmd_name == "resume":
                    dnd_manager.resume()
                    app_logger.info("DND desactivado por comando de control.")

            now = datetime.now(timezone.utc)
            pipeline.step(now)

            # Publicar estado en vivo para consultas inmediatas del CLI status
            runtime.write_state(
                {
                    "pid": current_pid,
                    "session_id": session_id,
                    "started_at": session_id.replace("session_", ""),
                    "is_paused": dnd_manager.is_paused,
                    "pause_reason": getattr(dnd_manager, "_pause_reason", ""),
                    "no_audio": args.no_audio,
                    "verbosity": args.verbosity or "normal",
                    "collectors": {
                        "system": health_manager.get_state("system").value,
                        "processes": health_manager.get_state("processes").value,
                        "psi": health_manager.get_state("psi").value,
                        "battery": health_manager.get_state("battery").value,
                    },
                    "gemini": {
                        "enabled": settings.gemini.enabled,
                        "state": health_manager.get_state("gemini").value,
                        "can_attempt": health_manager.can_attempt("gemini"),
                    },
                    "audio": {
                        "primary": "piper",
                        "state": health_manager.get_state("audio").value,
                        "no_audio": args.no_audio,
                    },
                    "dnd": {
                        "active": dnd_manager.is_paused,
                        "microphone_in_use": dnd_manager.is_microphone_in_use(),
                        "camera_in_use": dnd_manager.is_camera_in_use(),
                    },
                    "events_count": event_repo.count_events_for_session(session_id),
                }
            )

            count += 1
            time.sleep(step_interval)

    except KeyboardInterrupt:
        app_logger.info("Interrupción por teclado (Ctrl+C). Finalizando...")
    finally:
        pipeline.stop()
        audio_manager.shutdown()
        db.stop()
        runtime.remove_pid()
        app_logger.info("Ubuntu Voice Monitor cerrado correctamente.")

    return 0


def proc_pid() -> int:
    import os

    return os.getpid()


def cmd_stop(runtime: RuntimeManager) -> int:
    """Ejecuta el subcomando `stop`."""
    pid = runtime.get_running_pid()
    if pid is None:
        print("Ubuntu Voice Monitor no está en ejecución.")
        return 0

    print(f"Deteniendo Ubuntu Voice Monitor (PID: {pid})...")
    stopped = runtime.stop_daemon(timeout_s=3.0)
    if stopped:
        print("Ubuntu Voice Monitor se detuvo correctamente.")
        return 0
    print("Aviso: No se pudo verificar la detención del proceso.")
    return 1


def cmd_status(
    args: argparse.Namespace, runtime: RuntimeManager
) -> int:
    """Muestra el estado completo de collectors, Gemini, audio, sesión y DND.

    Garantiza funcionamiento incluso cuando Gemini está totalmente desconectado.
    """
    settings = load_settings_safely(args.config)
    pid = runtime.get_running_pid()
    state = runtime.read_state() if pid is not None else None

    # Estado de Gemini evaluado sin llamadas bloqueantes ni dependencias de red
    gemini_key_present = bool(settings.gemini.api_key)
    gemini_enabled = settings.gemini.enabled

    if not gemini_enabled:
        gemini_summary = "DESHABILITADO (config)"
    elif not gemini_key_present:
        gemini_summary = "DESCONECTADO (sin API key)"
    else:
        if state and state.get("gemini"):
            g_st = state["gemini"].get("state", "OK")
            can_att = state["gemini"].get("can_attempt", True)
            if not can_att or g_st != "OK":
                gemini_summary = f"DEGRADADO / CIRCUIT OPEN ({g_st})"
            else:
                gemini_summary = "CONECTADO / LISTO"
        else:
            gemini_summary = "CONFIGURADO (listo para conectar)"

    # Detección de plataforma y capacidades (MR 17)
    caps = PlatformDetector().detect()

    # Estado de DND
    dnd_manager = DNDManager()
    mic_busy = dnd_manager.is_microphone_in_use()
    cam_busy = dnd_manager.is_camera_in_use()
    is_dnd = bool(state and state.get("dnd", {}).get("active")) or mic_busy or cam_busy

    status_data: dict[str, Any] = {
        "status": "RUNNING" if pid is not None else "STOPPED",
        "pid": pid,
        "platform": {
            "distro": caps.distro.pretty_name,
            "is_wsl": caps.is_wsl,
            "wsl_version": caps.wsl_version,
            "systemd": caps.has_systemd,
            "user_systemd": caps.has_user_systemd,
            "dbus": caps.has_dbus,
            "journald": caps.has_journald,
            "audio_backend": caps.audio_backend.value,
            "psi": caps.has_psi,
            "battery": caps.has_battery,
            "warnings": list(caps.warnings),
        },
        "session": {
            "id": state.get("session_id") if state else "N/A",
            "events_detected": state.get("events_count", 0) if state else 0,
        },
        "collectors": {
            "system": (state and state.get("collectors", {}).get("system")) or "OK",
            "processes": (state and state.get("collectors", {}).get("processes"))
            or "OK",
            "psi": (state and state.get("collectors", {}).get("psi"))
            or ("OK" if caps.has_psi else "DEGRADED"),
            "battery": (state and state.get("collectors", {}).get("battery"))
            or ("OK" if caps.has_battery else "DEGRADED"),
            "systemd": (state and state.get("collectors", {}).get("systemd"))
            or ("OK" if caps.has_systemd else "DISABLED"),
            "journald": (state and state.get("collectors", {}).get("journald"))
            or ("OK" if caps.has_journald else "DISABLED"),
        },
        "gemini": {
            "enabled": gemini_enabled,
            "configured": gemini_key_present,
            "summary": gemini_summary,
        },
        "audio": {
            "mode": "NO-AUDIO"
            if (state and state.get("no_audio"))
            else "ACTIVO (Voz)",
            "primary_engine": "Piper TTS (Primordial)",
            "fallbacks": ["espeak-ng", "Gemini Audio"],
        },
        "dnd": {
            "active": is_dnd,
            "microphone_in_use": mic_busy,
            "camera_in_use": cam_busy,
            "reason": (state and state.get("pause_reason"))
            or ("sensores_ocupados" if (mic_busy or cam_busy) else ""),
        },
    }

    if args.json:
        print(json.dumps(status_data, indent=2))
        return 0

    # Presentación formateada en consola
    print("=" * 60)
    print("          ESTADO DE UBUNTU VOICE MONITOR          ")
    print("=" * 60)
    pid_info = f" (PID: {pid})" if pid else ""
    print(f"Estado General:     {status_data['status']}{pid_info}")
    print(f"Sesión Activa:      {status_data['session']['id']}")
    print(f"Eventos en sesión:  {status_data['session']['events_detected']}")
    print("-" * 60)
    print("[0] PLATAFORMA Y SUBSISTEMAS (MR 17):")
    p: dict[str, Any] = status_data["platform"]
    wsl_str = f"Sí (v{p['wsl_version']})" if p["is_wsl"] else "No (Linux nativo)"
    print(f"  - Distribución:    {p['distro']}")
    print(f"  - Entorno WSL:     {wsl_str}")
    print(f"  - systemd:         {'Activo' if p['systemd'] else 'No disponible'}")
    print(f"  - systemd Usuario: {'Activo' if p['user_systemd'] else 'No disponible'}")
    print(f"  - D-Bus:           {'Accesible' if p['dbus'] else 'No disponible'}")
    print(f"  - journald:        {'Accesible' if p['journald'] else 'No disponible'}")
    print(f"  - Audio Backend:   {p['audio_backend'].upper()}")
    print(f"  - Presión PSI:     {'Disponible' if p['psi'] else 'No soportado'}")
    print(f"  - Batería Física:  {'Detectada' if p['battery'] else 'No disponible'}")
    if p["warnings"]:
        print("  - Diagnóstico / Advertencias:")
        for w in p["warnings"]:
            print(f"    * {w}")
    print("-" * 60)
    print("[1] RECOLECTORES (COLLECTORS):")
    collectors: dict[str, Any] = status_data["collectors"]
    for k, v in collectors.items():
        print(f"  - {k.capitalize():15}: {v}")
    print("-" * 60)
    print("[2] INTELIGENCIA ARTIFICIAL (GEMINI):")
    gemini_info: dict[str, Any] = status_data["gemini"]
    print(f"  - Habilitado:      {gemini_info['enabled']}")
    api_key_str = "Presente" if gemini_info["configured"] else "Ausente"
    print(f"  - API Key:         {api_key_str}")
    print(f"  - Diagnóstico:     {gemini_info['summary']}")
    print("-" * 60)
    print("[3] SALIDA DE AUDIO:")
    audio_info: dict[str, Any] = status_data["audio"]
    print(f"  - Modo:            {audio_info['mode']}")
    print(f"  - Motor Primordial:{audio_info['primary_engine']}")
    print("-" * 60)
    print("[4] MODO NO MOLESTAR (DND):")
    print(f"  - Estado DND:      {'ACTIVO' if is_dnd else 'INACTIVO'}")
    dnd_info: dict[str, Any] = status_data["dnd"]
    if dnd_info["reason"]:
        print(f"  - Motivo:          {dnd_info['reason']}")
    print(f"  - Micrófono ocupado: {dnd_info['microphone_in_use']}")
    print(f"  - Cámara ocupada:    {dnd_info['camera_in_use']}")
    print("=" * 60)

    return 0


def cmd_pause(args: argparse.Namespace, runtime: RuntimeManager) -> int:
    """Pausa la narración por audio activando DND."""
    pid = runtime.get_running_pid()
    runtime.send_command("pause", reason=args.reason)
    if pid is not None:
        print(f"Narración pausada correctamente en el monitor activo (PID: {pid}).")
    else:
        print("Modo No Molestar registrado para el próximo inicio del monitor.")
    return 0


def cmd_resume(runtime: RuntimeManager) -> int:
    """Reanuda la narración por audio desactivando DND."""
    pid = runtime.get_running_pid()
    runtime.send_command("resume")
    if pid is not None:
        print(f"Narración reanudada correctamente en el monitor activo (PID: {pid}).")
    else:
        print("Modo No Molestar desactivado.")
    return 0


def cmd_session(
    args: argparse.Namespace, runtime: RuntimeManager
) -> int:
    """Muestra información y métricas de las sesiones registradas en SQLite."""
    settings = load_settings_safely(args.config)
    db = BackgroundDatabase(settings.storage.db_path)
    session_repo = SessionRepository(db)

    try:
        if args.list:
            sessions = session_repo.list_sessions(limit=10)
            if not sessions:
                print("No hay sesiones registradas en la base de datos.")
                return 0
            print("=" * 60)
            print(f"{'ID SESIÓN':<28} | {'INICIO':<19} | {'ESTADO'}")
            print("-" * 60)
            for s in sessions:
                st = "FINALIZADA" if s.get("ended_at") else "EN CURSO"
                start_fmt = (s.get("started_at") or "")[:19].replace("T", " ")
                print(f"{s['id']:<28} | {start_fmt:<19} | {st}")
            print("=" * 60)
            return 0

        # Mostrar sesión específica o la última
        target_id = args.id
        if not target_id:
            latest = session_repo.get_latest_session()
            if not latest:
                print("No hay sesiones registradas en la base de datos.")
                return 0
            target_id = latest["id"]

        report_svc = ReportService(settings.storage.db_path)
        data = report_svc.fetch_report_data(target_id)

        print("=" * 60)
        print(f"               SESIÓN: {data.session_id}               ")
        print("=" * 60)
        print(f"Inicio:          {data.started_at[:19].replace('T', ' ')}")
        print(f"Duración:        {data.duration_str}")
        print(f"Eventos Totales: {data.total_events}")
        cpu_str = f"{data.cpu_peak}%" if data.cpu_peak is not None else "No registrado"
        mem_str = (
            f"{data.memory_peak}%" if data.memory_peak is not None else "No registrado"
        )
        print(f"Pico CPU:        {cpu_str}")
        print(f"Pico Memoria:    {mem_str}")
        print(f"Confianza:       {data.confidence_level.upper()}")
        print("-" * 60)
        print(f"Resumen: {data.summary}")
        if data.unusual_events:
            print("-" * 60)
            print("Eventos inusuales o de riesgo:")
            for ev in data.unusual_events:
                print(f"  - [{ev['severity']}] {ev['summary']}")
        print("=" * 60)
        return 0

    finally:
        db.stop()


def cmd_report(
    args: argparse.Namespace, runtime: RuntimeManager
) -> int:
    """Genera informe en HTML, PDF o ambos formatos a partir de SQLite."""
    settings = load_settings_safely(args.config)
    report_svc = ReportService(settings.storage.db_path)

    target_session = args.session
    fmt = args.format.lower()

    try:
        # Determinar nombre base del reporte
        data = report_svc.fetch_report_data(target_session)
        sess_name = data.session_id.replace(" ", "_")

        out_path = Path(args.output) if args.output else Path.cwd()

        generated_files: list[Path] = []

        if fmt in ("html", "all"):
            if out_path.suffix.lower() == ".html":
                html_dest = out_path
            elif out_path.is_dir():
                html_dest = out_path / f"report_{sess_name}.html"
            else:
                html_dest = out_path
            saved_html = report_svc.save_html(html_dest, target_session)
            print(f"Informe HTML generado exitosamente: {saved_html.resolve()}")
            generated_files.append(saved_html)

        if fmt in ("pdf", "all"):
            if out_path.suffix.lower() == ".pdf":
                pdf_dest = out_path
            elif out_path.is_dir():
                pdf_dest = out_path / f"report_{sess_name}.pdf"
            else:
                pdf_dest = out_path
            try:
                saved_pdf = report_svc.save_pdf(pdf_dest, target_session)
                print(f"Informe PDF generado exitosamente:  {saved_pdf.resolve()}")
                generated_files.append(saved_pdf)
            except RuntimeError as exc:
                print(f"Aviso PDF: {exc}")
                if fmt == "pdf":
                    return 1

        return 0

    except Exception as exc:
        print(f"Error generando informe: {exc}", file=sys.stderr)
        return 1


def cmd_service(args: argparse.Namespace) -> int:
    """Gestiona el ciclo de vida del servicio systemd de usuario (MR 17)."""
    action = getattr(args, "action", "status")

    default_unit_path = (
        Path.home() / ".config" / "systemd" / "user" / "voice-monitor.service"
    )
    unit_path = (
        Path(args.unit_path)
        if getattr(args, "unit_path", None)
        else default_unit_path
    )

    if action == "install":
        # Verificación de seguridad: no instalar como root
        getuid_fn = getattr(os, "getuid", None)
        if callable(getuid_fn) and getuid_fn() == 0:  # pylint: disable=not-callable
            print(
                "ERROR: No se debe instalar el servicio como root.",
                file=sys.stderr,
            )
            print("Ejecute como su usuario normal sin sudo.", file=sys.stderr)
            return 1

        template_path = (
            Path(__file__).resolve().parent.parent
            / "packaging"
            / "systemd"
            / "voice-monitor.service"
        )
        if not template_path.is_file():
            print(
                f"ERROR: No se encontró la plantilla en {template_path}",
                file=sys.stderr,
            )
            return 1

        content = template_path.read_text(encoding="utf-8")
        narrator_bin = shutil.which("narrator")
        if not narrator_bin:
            narrator_bin = str(Path.home() / ".local" / "bin" / "narrator")

        # Ajustar ExecStart con la ruta real del binario
        lines = []
        for line in content.splitlines():
            if line.startswith("ExecStart="):
                lines.append(f"ExecStart={narrator_bin} start --foreground")
            else:
                lines.append(line)
        adjusted_content = "\n".join(lines) + "\n"

        unit_path.parent.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(adjusted_content, encoding="utf-8")
        print(f"[✓] Servicio systemd de usuario instalado en: {unit_path}")

        cfg_dir = Path.home() / ".config" / "ubuntu-voice-monitor"
        cfg_dir.mkdir(parents=True, exist_ok=True)

        if shutil.which("systemctl"):
            try:
                subprocess.run(
                    ["systemctl", "--user", "daemon-reload"],
                    check=False,
                    capture_output=True,
                )
                print("[✓] systemctl --user daemon-reload ejecutado.")
            except Exception:
                pass

        print("\nPara habilitar e iniciar el servicio ahora:")
        print("  systemctl --user enable --now voice-monitor.service")
        print("Para ver los logs:")
        print("  journalctl --user -u voice-monitor -f")
        return 0

    elif action == "uninstall":
        if shutil.which("systemctl"):
            try:
                subprocess.run(
                    ["systemctl", "--user", "stop", "voice-monitor.service"],
                    check=False,
                    capture_output=True,
                )
                subprocess.run(
                    ["systemctl", "--user", "disable", "voice-monitor.service"],
                    check=False,
                    capture_output=True,
                )
            except Exception:
                pass

        if unit_path.exists():
            unit_path.unlink()
            print(f"[✓] Archivo de servicio eliminado: {unit_path}")
        else:
            print(f"Aviso: El archivo de servicio no existe en {unit_path}")

        if shutil.which("systemctl"):
            try:
                subprocess.run(
                    ["systemctl", "--user", "daemon-reload"],
                    check=False,
                    capture_output=True,
                )
            except Exception:
                pass

        print("Desinstalación del servicio de usuario completada.")
        return 0

    elif action == "status":
        exists = unit_path.exists()
        print(
            f"Archivo de servicio ({unit_path}): "
            f"{'INSTALADO' if exists else 'NO INSTALADO'}"
        )
        if shutil.which("systemctl"):
            try:
                res = subprocess.run(
                    ["systemctl", "--user", "status", "voice-monitor.service"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                print("\nEstado de systemd (--user):")
                print(res.stdout or res.stderr)
            except Exception as exc:
                print(f"No se pudo consultar systemctl --user: {exc}")
        return 0

    elif action in ("start", "stop", "restart"):
        if not shutil.which("systemctl"):
            print(
                "ERROR: 'systemctl' no está disponible en este sistema.",
                file=sys.stderr,
            )
            return 1
        try:
            res = subprocess.run(
                ["systemctl", "--user", action, "voice-monitor.service"],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                print(
                    f"Comando 'systemctl --user {action} voice-monitor.service' "
                    "ejecutado con éxito."
                )
                return 0
            else:
                msg = res.stderr or res.stdout
                print(f"Error ({res.returncode}): {msg}", file=sys.stderr)
                return res.returncode
        except Exception as exc:
            print(f"Error invocando systemctl: {exc}", file=sys.stderr)
            return 1

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada de la CLI de `narrator`."""
    parser = build_parser()
    args = parser.parse_args(argv)

    runtime = RuntimeManager()

    if args.command == "start":
        return cmd_start(args, runtime)
    elif args.command == "stop":
        return cmd_stop(runtime)
    elif args.command == "status":
        return cmd_status(args, runtime)
    elif args.command == "pause":
        return cmd_pause(args, runtime)
    elif args.command == "resume":
        return cmd_resume(runtime)
    elif args.command == "session":
        return cmd_session(args, runtime)
    elif args.command == "report":
        return cmd_report(args, runtime)
    elif args.command == "service":
        return cmd_service(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
