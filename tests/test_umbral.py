"""Pruebas de la opción ``--umbral`` y de los umbrales configurables del detector."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.cli import _umbral_type, build_parser, cmd_umbral, main, persist_env_var
from app.core.config import Settings


def test_umbral_defaults() -> None:
    settings = Settings()
    assert settings.detector.cpu_threshold == 80.0
    assert settings.detector.app_cpu_threshold == 25.0


def test_umbral_from_env_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("DETECTOR_CPU_THRESHOLD=55\n", encoding="utf-8")
    assert Settings.load(env_file=env).detector.cpu_threshold == 55.0


@pytest.mark.parametrize("value", ["0", "101", "-5", "abc", "7.5"])
def test_umbral_type_rejects_invalid(value: str) -> None:
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        _umbral_type(value)


def test_umbral_global_option_parses_with_and_without_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(["--umbral", "70"])
    assert args.umbral == 70 and args.command is None
    args = parser.parse_args(["--umbral", "60", "start", "-f"])
    assert args.umbral == 60 and args.command == "start"
    args = parser.parse_args(["--threshold", "50"])
    assert args.umbral == 50


def test_persist_env_var_creates_and_updates(tmp_path: Path) -> None:
    env = tmp_path / "sub" / "config.env"
    persist_env_var(env, "DETECTOR_CPU_THRESHOLD", "70")
    persist_env_var(env, "OTHER", "x")
    persist_env_var(env, "DETECTOR_CPU_THRESHOLD", "40")
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines == ["DETECTOR_CPU_THRESHOLD=40", "OTHER=x"]


def test_cmd_umbral_saves_and_notifies_running_monitor(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    runtime = MagicMock()
    runtime.get_running_pid.return_value = 1234
    args = build_parser().parse_args(["--umbral", "65", "--config", str(env)])
    assert cmd_umbral(args, runtime) == 0
    assert "DETECTOR_CPU_THRESHOLD=65" in env.read_text(encoding="utf-8")
    runtime.send_command.assert_called_once_with("threshold", value=65)


def test_cmd_umbral_without_running_monitor_only_saves(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    runtime = MagicMock()
    runtime.get_running_pid.return_value = None
    args = build_parser().parse_args(["--umbral", "65", "--config", str(env)])
    assert cmd_umbral(args, runtime) == 0
    runtime.send_command.assert_not_called()


def test_main_without_args_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "narrator" in capsys.readouterr().out
