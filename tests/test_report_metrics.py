"""Pruebas de las métricas del equipo en el informe HTML."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.host_metrics import (
    build_line_chart,
    collect_host_metrics,
    format_bytes,
    format_uptime,
)
from app.core.reports import ReportService
from app.storage.db import BackgroundDatabase

START = datetime(2026, 10, 13, 11, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def service(tmp_path: Path) -> ReportService:
    db_file = tmp_path / "metrics.db"
    db = BackgroundDatabase(db_file)
    db.fetch_sync(
        "INSERT INTO sessions (id, started_at, ended_at) VALUES (?, ?, ?)",
        ("session_m_1", START.isoformat(), None),
    )
    for minute in range(4):
        ts = (START + timedelta(minutes=minute)).isoformat()
        for metric, avg in (("cpu", 10.0 + minute * 20), ("memory", 40.0)):
            db.fetch_sync(
                "INSERT INTO minute_agg (id, session_id, minute_timestamp, "
                "metric_name, min_val, max_val, avg_val, count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"{metric}-{minute}", "session_m_1", ts, metric,
                 avg - 5, avg + 5, avg, 12),
            )
    db.stop()
    return ReportService(db_file)


def test_format_helpers() -> None:
    assert format_bytes(512) == "512 B"
    assert format_bytes(1024 * 1024 * 1.5) == "1.5 MB"
    assert format_uptime(90061) == "1d 1h 1m"
    assert format_uptime(120) == "0h 2m"


def test_collect_host_metrics_has_expected_sections() -> None:
    metrics = collect_host_metrics()
    labels = {g["label"] for g in metrics["gauges"]}
    assert {"CPU", "Memoria"} <= labels
    assert all(0 <= g["percent"] <= 100 for g in metrics["gauges"])
    assert any(label == "Kernel" for label, _ in metrics["info"])
    assert metrics["captured_at"].endswith("UTC")


def test_build_line_chart_needs_two_points() -> None:
    assert build_line_chart([]) == ""
    assert build_line_chart([(START.isoformat(), 1.0, 2.0)]) == ""
    svg = build_line_chart(
        [(START.isoformat(), 10.0, 20.0),
         ((START + timedelta(minutes=1)).isoformat(), 50.0, 90.0)]
    )
    assert svg.startswith("<svg") and "polyline" in svg and "11:00" in svg


def test_report_html_contains_host_metrics_and_charts(
    service: ReportService,
) -> None:
    html = service.generate_html("session_m_1")
    assert "Métricas del equipo" in html
    assert "CPU durante la sesión" in html
    assert html.count("<svg") == 2
    assert "Procesos con más memoria" in html


def test_report_html_without_series_shows_hint(tmp_path: Path) -> None:
    db_file = tmp_path / "empty.db"
    db = BackgroundDatabase(db_file)
    db.fetch_sync(
        "INSERT INTO sessions (id, started_at, ended_at) VALUES (?, ?, ?)",
        ("session_e", START.isoformat(), None),
    )
    db.stop()
    html = ReportService(db_file).generate_html("session_e")
    assert "Aún no hay datos suficientes" in html
    assert "<svg" not in html
