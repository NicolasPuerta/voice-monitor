"""Pruebas del generador de informes ReportService (MR 15).

Verifica agregación de métricas, picos de CPU/RAM, sanitización de secretos,
manejo de datos ausentes (sin invención), generación HTML y exportación PDF.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.privacy import PrivacySanitizer
from app.core.reports import ReportService, SessionReportData
from app.storage.db import BackgroundDatabase


@pytest.fixture
def sample_db(tmp_path: Path) -> Path:
    """Crea una base de datos SQLite poblada con eventos de prueba."""
    db_file = tmp_path / "test_events.db"
    db = BackgroundDatabase(db_file)

    session_id = "session_test_123"
    start_time = datetime(2026, 10, 13, 10, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 10, 13, 10, 45, 30, tzinfo=timezone.utc)

    # 1. Sesión
    db.fetch_sync(
        "INSERT INTO sessions (id, started_at, ended_at) VALUES (?, ?, ?)",
        (session_id, start_time.isoformat(), end_time.isoformat()),
    )

    # 2. Eventos con datos variados, incluyendo secretos a sanitizar
    events_data = [
        # Evento 1: CPU spike crítico con ruta de usuario a sanitizar
        (
            "ev-1",
            session_id,
            "cpu_spike",
            "CRITICAL",
            "alta",
            "SPOKEN",
            88.5,
            0.85,
            0.6,
            0.9,
            0.8,
            0.9,
            0.0,
            "2026-10-13T10:05:00+00:00",
            "/home/usuario/app/ffmpeg",
            (
                "Uso extremo de CPU (98.5%) ejecutando /home/usuario/app/ffmpeg "
                "token Bearer secret123"
            ),
            json.dumps({"cpu_percent": 98.5, "memory_percent": 65.0}),
        ),
        # Evento 2: DND suprimido por micrófono
        (
            "ev-2",
            session_id,
            "system_pressure",
            "HIGH",
            "alta",
            "DND",
            72.0,
            0.7,
            0.4,
            0.6,
            0.6,
            0.7,
            0.0,
            "2026-10-13T10:15:00+00:00",
            "gnome-shell",
            "Presión alta en sistema",
            json.dumps({
                "dnd_suppressed": "true",
                "dnd_reason": "sensor:microphone_in_use",
                "cpu_percent": 75.0,
                "memory_percent": 82.0,
            }),
        ),
        # Evento 3: Ciclo de vida de proceso (proceso zombie / died)
        (
            "ev-3",
            session_id,
            "zombie_process",
            "MEDIUM",
            "media",
            "THRESHOLD_OMITTED",
            40.0,
            0.4,
            0.3,
            0.5,
            0.3,
            0.4,
            0.0,
            "2026-10-13T10:20:00+00:00",
            "worker_proc",
            "Proceso zombie detectado en background",
            json.dumps({"pid": 9876}),
        ),
    ]

    for ev in events_data:
        db.fetch_sync(
            """
            INSERT INTO events (
                id, session_id, event_type, severity, confidence, decision,
                score, impact, novelty, anomaly, risk, relevance, repetition_penalty,
                detected_at, app_key, summary, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ev,
        )

    # 3. Fuente degradada registrada
    db.fetch_sync(
        """
        INSERT INTO source_health (id, session_id, source, state, reason, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "h-1",
            session_id,
            "gemini",
            "DEGRADED",
            "Timeout de conexión a https://api.google.com/key=AKIAIOSFODNN7EXAMPLE",
            "2026-10-13T10:10:00+00:00",
        ),
    )

    # 4. Agregados por minuto (pico de CPU y memoria)
    agg_sql = """
        INSERT INTO minute_agg (
            id, session_id, minute_timestamp, metric_name, min_val, max_val,
            avg_val, count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    db.fetch_sync(
        agg_sql,
        ("agg-1", session_id, "2026-10-13T10:05:00", "cpu", 40.0, 98.5, 75.0, 12),
    )
    db.fetch_sync(
        agg_sql,
        ("agg-2", session_id, "2026-10-13T10:15:00", "memory", 60.0, 85.0, 72.0, 12),
    )

    db.stop()
    return db_file


def test_report_service_extracts_and_aggregates_session_data(sample_db: Path) -> None:
    """Verifica agregación de duración, aplicaciones, picos y salud."""
    service = ReportService(sample_db)
    data: SessionReportData = service.fetch_report_data("session_test_123")

    assert data.session_id == "session_test_123"
    assert "45m 30s" in data.duration_str
    assert data.total_events == 3

    # Picos de CPU y memoria detectados
    assert data.cpu_peak == 98.5
    assert data.memory_peak == 85.0

    # Fuentes degradadas
    assert len(data.degraded_sources) == 1
    assert data.degraded_sources[0]["source"] == "gemini"
    assert data.degraded_sources[0]["state"] == "DEGRADED"

    # Procesos abiertos/cerrados/zombie
    assert len(data.process_activity) == 1
    assert data.process_activity[0]["type"] == "zombie_process"

    # Periodos DND
    assert len(data.dnd_periods) == 1
    assert "microphone_in_use" in data.dnd_periods[0]["reason"]

    # Eventos inusuales o de riesgo
    assert len(data.unusual_events) >= 1
    assert data.unusual_events[0]["severity"] == "CRITICAL"


def test_report_service_sanitizes_sensitive_information(sample_db: Path) -> None:
    """Asegura que tokens, credenciales y rutas de usuario sean redactadas."""
    sanitizer = PrivacySanitizer()
    service = ReportService(sample_db, sanitizer=sanitizer)
    data = service.fetch_report_data("session_test_123")

    # Verificar que el Bearer token no aparezca en eventos inusuales ni top apps
    summaries = [ev["summary"] for ev in data.unusual_events]
    assert not any("secret123" in s for s in summaries)
    assert any("Bearer ***" in s for s in summaries)

    # Verificar que la key de AWS/Google en fuente degradada fue redactada
    for deg in data.degraded_sources:
        assert "AKIAIOSFODNN7EXAMPLE" not in deg["reason"]


def test_report_service_handles_missing_data_without_inventing(tmp_path: Path) -> None:
    """Verifica que campos sin datos muestren 'No registrado' en vez de inventar."""
    empty_db = tmp_path / "empty_session.db"
    db = BackgroundDatabase(empty_db)

    session_id = "session_minimal"
    start_time = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    db.fetch_sync(
        "INSERT INTO sessions (id, started_at, ended_at) VALUES (?, ?, ?)",
        (session_id, start_time.isoformat(), None),
    )
    db.stop()

    service = ReportService(empty_db)
    data = service.fetch_report_data(session_id)

    assert data.total_events == 0
    assert data.cpu_peak is None
    assert data.memory_peak is None
    assert len(data.process_activity) == 0
    assert len(data.unusual_events) == 0
    assert len(data.degraded_sources) == 0
    assert "en curso" in data.duration_str

    html = service.generate_html(session_id)
    assert "No registrado" in html
    assert "Sin cambios anómalos de procesos registrados" in html
    assert "Todas las fuentes operaron normalmente" in html


def test_report_service_generate_and_save_html(sample_db: Path, tmp_path: Path) -> None:
    """Verifica la generación y guardado de informe HTML en disco."""
    service = ReportService(sample_db)
    out_file = tmp_path / "report.html"

    saved_path = service.save_html(out_file, "session_test_123")
    assert saved_path.exists()
    content = saved_path.read_text(encoding="utf-8")

    assert "<!DOCTYPE html>" in content
    assert "Informe de Sesión: session_test_123" in content
    assert "98.5%" in content
    assert "CRITICAL" in content


def test_report_service_pdf_generation_with_weasyprint_mock(sample_db: Path) -> None:
    """Verifica la generación de PDF cuando WeasyPrint está presente."""
    service = ReportService(sample_db)

    mock_weasy = MagicMock()
    mock_doc = MagicMock()
    mock_doc.write_pdf.return_value = b"%PDF-1.4 mock bytes"
    mock_weasy.HTML.return_value = mock_doc

    with patch.dict("sys.modules", {"weasyprint": mock_weasy}):
        pdf_bytes = service.generate_pdf("session_test_123")
        assert pdf_bytes == b"%PDF-1.4 mock bytes"


def test_report_service_pdf_fallback_when_weasyprint_unavailable(sample_db: Path) -> None:
    """Verifica que se lance un error informativo cuando WeasyPrint no está instalado."""
    service = ReportService(sample_db)

    with patch.dict("sys.modules", {"weasyprint": None}):
        with pytest.raises(RuntimeError) as exc_info:
            service.generate_pdf("session_test_123")
        assert "WeasyPrint no está disponible" in str(exc_info.value)
        assert "pip install weasyprint" in str(exc_info.value)
