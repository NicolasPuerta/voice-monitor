"""Pruebas del comando CLI `narrator` (MR 15).

Verifica todos los subcomandos (start, stop, status, pause, resume, session, report),
las opciones globales (--verbosity, --no-audio, --debug, --config), el comportamiento
cuando Gemini está desconectado y el ciclo de vida del proceso y DND.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.cli import build_parser, main
from app.core.runtime import RuntimeManager
from app.storage.db import BackgroundDatabase


@pytest.fixture
def cli_env(tmp_path: Path) -> tuple[Path, RuntimeManager]:
    """Crea un entorno de prueba con base de datos y RuntimeManager aislado."""
    db_file = tmp_path / "test_cli.db"
    db = BackgroundDatabase(db_file)

    session_id = "session_cli_100"
    start_time = datetime(2026, 10, 13, 11, 0, 0, tzinfo=timezone.utc)

    db.fetch_sync(
        "INSERT INTO sessions (id, started_at, ended_at) VALUES (?, ?, ?)",
        (session_id, start_time.isoformat(), None),
    )
    db.fetch_sync(
        """
        INSERT INTO events (
            id, session_id, event_type, severity, confidence, decision,
            score, impact, novelty, anomaly, risk, relevance, repetition_penalty,
            detected_at, app_key, summary, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ev-1",
            session_id,
            "cpu_spike",
            "CRITICAL",
            "alta",
            "SPOKEN",
            85.0,
            0.8,
            0.5,
            0.8,
            0.7,
            0.8,
            0.0,
            start_time.isoformat(),
            "test_app",
            "Alto consumo de CPU",
            json.dumps({"cpu_percent": 92.0}),
        ),
    )
    db.stop()

    runtime_dir = tmp_path / "runtime"
    runtime_mgr = RuntimeManager(runtime_dir)

    return db_file, runtime_mgr


def test_cli_parser_builds_and_recognizes_subcommands() -> None:
    """Verifica que el parser incluya todos los subcomandos y opciones globales."""
    parser = build_parser()

    # Opciones globales
    args = parser.parse_args([
        "--verbosity", "verbose",
        "--no-audio",
        "--debug",
        "status",
    ])
    assert args.command == "status"
    assert args.verbosity == "verbose"
    assert args.no_audio is True
    assert args.debug is True

    # Subcomandos válidos
    for cmd in [
        "start", "stop", "status", "pause", "resume", "session", "report", "service"
    ]:
        parsed = parser.parse_args([cmd])
        assert parsed.command == cmd


def test_cli_status_works_when_stopped(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Verifica `narrator status` cuando el monitor no está en ejecución."""
    runtime = RuntimeManager(tmp_path / "rt")

    with patch("app.cli.RuntimeManager", return_value=runtime):
        code = main(["status"])

    assert code == 0
    out = capsys.readouterr().out
    assert "ESTADO DE UBUNTU VOICE MONITOR" in out
    assert "STOPPED" in out
    assert "PLATAFORMA Y SUBSISTEMAS" in out
    assert "RECOLECTORES (COLLECTORS)" in out
    assert "INTELIGENCIA ARTIFICIAL (GEMINI)" in out
    assert "SALIDA DE AUDIO" in out
    assert "MODO NO MOLESTAR (DND)" in out


def test_cli_status_works_when_gemini_is_disconnected(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Asegura que `status` funcione correctamente cuando Gemini está desconectado."""
    runtime = RuntimeManager(tmp_path / "rt")

    # Mock settings sin API key o deshabilitado
    mock_settings = MagicMock()
    mock_settings.gemini.enabled = True
    mock_settings.gemini.api_key = ""
    mock_settings.app.log_level = "INFO"

    with patch("app.cli.RuntimeManager", return_value=runtime), \
         patch("app.cli.load_settings_safely", return_value=mock_settings):
        code = main(["status"])

    assert code == 0
    out = capsys.readouterr().out
    assert "DESCONECTADO" in out or "Ausente" in out
    assert "STOPPED" in out


def test_cli_status_json_format(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Verifica la salida estructurada de `narrator status --json`."""
    runtime = RuntimeManager(tmp_path / "rt")

    with patch("app.cli.RuntimeManager", return_value=runtime):
        code = main(["status", "--json"])

    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "STOPPED"
    assert "collectors" in data
    assert "gemini" in data
    assert "audio" in data
    assert "dnd" in data


def test_cli_pause_and_resume_send_commands(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Verifica que `pause` y `resume` emitan señales de control DND."""
    runtime = RuntimeManager(tmp_path / "rt")

    with patch("app.cli.RuntimeManager", return_value=runtime):
        pause_code = main(["pause", "--reason", "llamada_zoom"])
        assert pause_code == 0
        cmd = runtime.consume_command()
        assert cmd is not None
        assert cmd["command"] == "pause"
        assert cmd["reason"] == "llamada_zoom"

        resume_code = main(["resume"])
        assert resume_code == 0
        cmd = runtime.consume_command()
        assert cmd is not None
        assert cmd["command"] == "resume"


def test_cli_session_command(
    cli_env: tuple[Path, RuntimeManager], capsys: pytest.CaptureFixture[str]
) -> None:
    """Verifica la visualización de detalles de sesión con `narrator session`."""
    db_file, runtime = cli_env

    mock_settings = MagicMock()
    mock_settings.storage.db_path = str(db_file)

    with patch("app.cli.RuntimeManager", return_value=runtime), \
         patch("app.cli.load_settings_safely", return_value=mock_settings):
        code = main(["session", "--id", "session_cli_100"])

    assert code == 0
    out = capsys.readouterr().out
    assert "SESIÓN: session_cli_100" in out
    assert "Alto consumo de CPU" in out


def test_cli_session_list(
    cli_env: tuple[Path, RuntimeManager], capsys: pytest.CaptureFixture[str]
) -> None:
    """Verifica el listado de sesiones con `narrator session --list`."""
    db_file, runtime = cli_env

    mock_settings = MagicMock()
    mock_settings.storage.db_path = str(db_file)

    with patch("app.cli.RuntimeManager", return_value=runtime), \
         patch("app.cli.load_settings_safely", return_value=mock_settings):
        code = main(["session", "--list"])

    assert code == 0
    out = capsys.readouterr().out
    assert "session_cli_100" in out
    assert "EN CURSO" in out


def test_cli_report_generation(
    cli_env: tuple[Path, RuntimeManager], tmp_path: Path
) -> None:
    """Verifica que `narrator report` genere el archivo HTML de reporte."""
    db_file, runtime = cli_env
    out_html = tmp_path / "informe.html"

    mock_settings = MagicMock()
    mock_settings.storage.db_path = str(db_file)

    with patch("app.cli.RuntimeManager", return_value=runtime), \
         patch("app.cli.load_settings_safely", return_value=mock_settings):
        code = main([
            "report",
            "--session", "session_cli_100",
            "--format", "html",
            "--output", str(out_html),
        ])

    assert code == 0
    assert out_html.exists()
    content = out_html.read_text(encoding="utf-8")
    assert "Informe de Sesión: session_cli_100" in content


def test_cli_start_foreground_executes_and_terminates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verifica que `narrator start --foreground` ejecute un ciclo controlado y salga."""
    runtime = RuntimeManager(tmp_path / "rt")

    db_path = tmp_path / "start_test.db"
    mock_settings = MagicMock()
    mock_settings.storage.db_path = str(db_path)
    mock_settings.gemini.enabled = False
    mock_settings.gemini.api_key = ""
    mock_settings.narration.piper_model_path = ""
    mock_settings.app.log_level = "INFO"
    mock_settings.dnd.enabled = False
    mock_settings.collector.interval_s = 0.01

    with patch("app.cli.RuntimeManager", return_value=runtime), \
         patch("app.cli.load_settings_safely", return_value=mock_settings):
        code = main([
            "start",
            "--foreground",
            "--iterations", "1",
            "--test-gemini",
            "--no-audio",
        ])

    assert code == 0
    # Al finalizar, el PID debe haber sido limpiado
    assert runtime.get_running_pid() is None


def test_cli_service_subcommand(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verifica la gestión del servicio systemd mediante `narrator service`."""
    unit_file = tmp_path / "voice-monitor.service"

    # 1. Status inicial (no instalado)
    code = main(["service", "status", "--unit-path", str(unit_file)])
    assert code == 0
    out = capsys.readouterr().out
    assert "NO INSTALADO" in out

    # 2. Install
    code = main(["service", "install", "--unit-path", str(unit_file)])
    assert code == 0
    out = capsys.readouterr().out
    assert "instalado en" in out
    assert unit_file.is_file()

    # 3. Status tras instalación
    code = main(["service", "status", "--unit-path", str(unit_file)])
    assert code == 0
    out = capsys.readouterr().out
    assert "INSTALADO" in out

    # 4. Uninstall
    code = main(["service", "uninstall", "--unit-path", str(unit_file)])
    assert code == 0
    assert not unit_file.exists()
