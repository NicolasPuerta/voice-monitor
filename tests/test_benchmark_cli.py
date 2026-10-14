"""Pruebas de integración del script benchmark.py (MR 14)."""

import json
import os
from pathlib import Path
import subprocess  # noqa: S404
import sys

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark.py"


def test_benchmark_cli_runs_and_reports_output(tmp_path: Path) -> None:
    """Verifica que benchmark.py ejecute un escenario y genere el reporte."""
    report_file = tmp_path / "report.json"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--ticks",
            "5",
            "--scenario",
            "idle",
            "--report-json",
            str(report_file),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "INFORME DE RENDIMIENTO" in result.stdout
    assert "OBJETIVOS DE CONSUMO" in result.stdout
    assert report_file.exists()

    with open(report_file, encoding="utf-8") as f:
        data = json.load(f)
    assert "resources" in data
    assert "scoring" in data


def test_benchmark_cli_rejects_invalid_scenario() -> None:
    """Verifica que un escenario no soportado sea rechazado con error."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--scenario", "non_existent"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode != 0
