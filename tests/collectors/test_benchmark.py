"""Prueba de humo del benchmark del ProcessCollector."""

import subprocess  # noqa: S404  # Test-only: runs the benchmark script
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "benchmark_process_collector.py"


def test_benchmark_script_runs_and_reports_timings() -> None:
    """Verifica que el benchmark termine bien e imprima el resumen."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--iterations", "2", "--warmup", "1"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert "Procesos vistos" in result.stdout
    assert "Tiempo por recolección" in result.stdout


def test_benchmark_rejects_invalid_iterations() -> None:
    """Verifica que --iterations menor que 1 sea rechazado."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--iterations", "0"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        encoding="utf-8",
    )
    assert result.returncode != 0
