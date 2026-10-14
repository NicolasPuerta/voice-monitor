"""Pruebas de la capa de almacenamiento y base de conocimiento."""

import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

import pytest

from app.storage.db import BackgroundDatabase
from app.storage.repositories import (
    EventRepository,
    KnowledgeRepository,
    SessionRepository,
)
from app.domain.events import Event, EventMetadata, ScoreResult, ScoreBreakdown
from app.domain.enums import EventType, EventSeverity, EventPriority, EventDecision

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def test_db(tmp_path: Path) -> BackgroundDatabase:
    db_file = tmp_path / "test.db"
    # Reducimos flush_interval para que sea casi inmediato en tests
    db = BackgroundDatabase(db_file, batch_size=2, flush_interval_s=0.1)
    yield db
    db.stop()


def test_db_initializes_and_seeds(test_db: BackgroundDatabase) -> None:
    # Esperar el flush inicial/seed
    rows = test_db.fetch_sync("SELECT count(*) as c FROM process_knowledge")
    count = rows[0]["c"]
    assert 200 <= count <= 300

    rows = test_db.fetch_sync("SELECT version FROM schema_version")
    assert rows[0]["version"] == 1


def test_session_repository(test_db: BackgroundDatabase) -> None:
    repo = SessionRepository(test_db)
    sess_id = str(uuid.uuid4())

    repo.start_session(sess_id, NOW)
    repo.end_session(sess_id, NOW)

    # Forzar el vaciado de la cola (es un worker asncrono, esperamos un momento rpido)
    time.sleep(0.2)

    rows = test_db.fetch_sync("SELECT * FROM sessions WHERE id = ?", (sess_id,))
    assert len(rows) == 1
    assert rows[0]["id"] == sess_id
    assert rows[0]["started_at"] == NOW.isoformat()
    assert rows[0]["ended_at"] == NOW.isoformat()


def test_event_repository_saves_full_event(test_db: BackgroundDatabase) -> None:
    repo = EventRepository(test_db)

    ev = Event(
        event_type=EventType.CPU_SPIKE,
        severity=EventSeverity.CRITICAL,
        summary="Test Event",
        metadata=EventMetadata(app_key="test_app"),
    )
    ev.decision = EventDecision.DEFERRED
    ev.score_result = ScoreResult(
        score=99.0,
        priority=EventPriority.CRITICAL,
        breakdown=ScoreBreakdown(
            impact=30.0,
            novelty=10.0,
            anomaly=10.0,
            risk=10.0,
            relevance=39.0,
            repetition_penalty=0.0,
        ),
        reasons=["Because"],
    )

    repo.save_event("sess-1", ev)

    # Test batch flush: metemos otro evento dummy
    ev2 = Event(
        event_type=EventType.CPU_SPIKE, severity=EventSeverity.LOW, summary="Dummy"
    )
    repo.save_event("sess-1", ev2)

    time.sleep(0.3)

    rows = test_db.fetch_sync("SELECT * FROM events WHERE id = ?", (str(ev.id),))
    assert len(rows) == 1
    row = rows[0]

    assert row["event_type"] == "cpu_spike"
    assert row["decision"] == "deferred"
    assert row["score"] == 99.0
    assert row["impact"] == 30.0
    assert row["app_key"] == "test_app"


def test_knowledge_repository_resolution(test_db: BackgroundDatabase) -> None:
    repo = KnowledgeRepository(test_db)

    # 1. Curated exact match
    ff = repo.get_knowledge("firefox", "firefox")
    assert ff.category == "browser"
    assert ff.source.value == "curated"

    # Verificación de servicios y subsistemas clave de Linux (MR 18)
    sysd = repo.get_knowledge("systemd-journald", "systemd-journald")
    assert sysd.category == "system"
    assert "journald" in sysd.short_text

    dock = repo.get_knowledge("dockerd", "dockerd")
    assert dock.category == "container"

    pg = repo.get_knowledge("postgres", "postgres")
    assert pg.category == "database"

    pw = repo.get_knowledge("pipewire", "pipewire")
    assert pw.category == "multimedia"

    # 2. Heuristic
    py = repo.get_knowledge("cmd:python script.py", "python3")
    assert py.source.value == "heuristic"
    assert "Python" in py.short_text

    # 3. Unknown Fallback
    unk = repo.get_knowledge("exe:/opt/custom/bin", "custom")
    assert unk.source.value == "unknown"
    assert "desconocida" in unk.short_text
    assert unk.confidence == "low"


def test_knowledge_base_schema_integrity(test_db: BackgroundDatabase) -> None:
    """Verifica que todas las entradas contengan texto descriptivo verificable."""
    entries = test_db.fetch_sync("SELECT * FROM process_knowledge")
    assert len(entries) >= 200

    categories = set()
    for row in entries:
        assert len(row["key"].strip()) > 0
        assert len(row["short_text"].strip()) > 0
        assert len(row["category"].strip()) > 0
        assert row["source"] in ("curated", "heuristic", "unknown")
        assert row["confidence"] in ("high", "medium", "low")
        assert row["version"] >= 1
        categories.add(row["category"])

    # Debe cubrir categorías clave
    assert "system" in categories
    assert "desktop" in categories
    assert "browser" in categories
    assert "database" in categories
    assert "container" in categories
    assert "network" in categories


def test_background_database_error_recovery(tmp_path: Path) -> None:
    db = BackgroundDatabase(tmp_path / "error.db", flush_interval_s=0.1)

    # Simulamos un query invlido. Esto har rollback silencioso de ese query
    db.execute_async("INSERT INTO no_existe (id) VALUES (1)")

    # Insertamos algo vlido luego para verificar que el worker sigue vivo
    db.execute_async(
        "INSERT INTO sessions (id, started_at) VALUES (?, ?)", ("s2", NOW.isoformat())
    )

    time.sleep(0.3)

    rows = db.fetch_sync("SELECT * FROM sessions WHERE id = 's2'")
    assert len(rows) == 1

    db.stop()
