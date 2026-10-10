"""Base de datos y persistencia asncrona para el monitor."""

import sqlite3
import threading
import queue
from pathlib import Path
from typing import Any

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence TEXT NOT NULL,
    decision TEXT,
    score REAL,
    impact REAL,
    novelty REAL,
    anomaly REAL,
    risk REAL,
    relevance REAL,
    repetition_penalty REAL,
    text_hash TEXT,
    detected_at TEXT NOT NULL,
    app_key TEXT,
    summary TEXT,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS minute_agg (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    minute_timestamp TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    min_val REAL,
    max_val REAL,
    avg_val REAL,
    count INTEGER
);

CREATE TABLE IF NOT EXISTS process_knowledge (
    key TEXT PRIMARY KEY,
    short_text TEXT NOT NULL,
    long_text TEXT,
    category TEXT,
    source TEXT,
    confidence TEXT,
    version INTEGER
);

CREATE TABLE IF NOT EXISTS explanation_cache (
    id TEXT PRIMARY KEY,
    app_key TEXT NOT NULL,
    explanation TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_health (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source TEXT NOT NULL,
    state TEXT NOT NULL,
    reason TEXT,
    updated_at TEXT NOT NULL
);
"""


class BackgroundDatabase:
    """Maneja las escrituras a SQLite en un hilo en background para no bloquear."""

    def __init__(
        self, db_path: Path | str, batch_size: int = 50, flush_interval_s: float = 2.0
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.batch_size = batch_size
        self.flush_interval_s = flush_interval_s
        self._queue: queue.Queue[tuple[str, tuple[Any, ...]] | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)

        # Migramos inmediatamente en el hilo principal antes de empezar
        self._init_db()
        self._thread.start()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")

            # Simple migration
            cursor = conn.cursor()
            cursor.execute(
                "SELECT count(name) FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            if cursor.fetchone()[0] == 0:
                conn.executescript(SCHEMA_V1)
                conn.execute("INSERT INTO schema_version (version) VALUES (1)")
            conn.commit()

            self._seed_knowledge(conn)

    def _seed_knowledge(self, conn: sqlite3.Connection) -> None:
        """Seed initial verifiable explanations for common processes."""
        seeds = [
            (
                "firefox",
                "Navegador web Firefox.",
                "Uso de CPU comn por renderizado y extensiones.",
                "browser",
                "curated",
                "high",
                1,
            ),
            (
                "systemd",
                "Administrador de sistema y servicios de Linux.",
                "PID 1. No debe consumir mucha CPU de forma sostenida.",
                "system",
                "curated",
                "high",
                1,
            ),
            (
                "bash",
                "Intrprete de comandos (shell).",
                "Bajo consumo esperado.",
                "shell",
                "curated",
                "high",
                1,
            ),
            (
                "gnome-shell",
                "Entorno de escritorio GNOME.",
                "Responsable de la UI, ventanas y animaciones.",
                "desktop",
                "curated",
                "high",
                1,
            ),
        ]
        conn.executemany(
            """INSERT OR IGNORE INTO process_knowledge 
               (key, short_text, long_text, category, source, confidence, version) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            seeds,
        )
        conn.commit()

    def _worker(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")

        batch = []

        def flush() -> None:
            if not batch:
                return
            try:
                for query, params in batch:
                    conn.execute(query, params)
                conn.commit()
            except sqlite3.Error:
                # En un entorno real se hara log del error
                conn.rollback()
            finally:
                batch.clear()

        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=self.flush_interval_s)
                if item is None:  # Sentinel
                    break
                batch.append(item)
                if len(batch) >= self.batch_size:
                    flush()
            except queue.Empty:
                flush()

        # Flush final al cerrar
        flush()
        conn.close()

    def execute_async(self, query: str, params: tuple[Any, ...] = ()) -> None:
        """Enva una consulta para ejecutarse asncronamente."""
        if self._stop_event.is_set():
            return
        self._queue.put((query, params))

    def fetch_sync(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        """Lee sncronamente. Utilizado raramente, ej. al iniciar."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put(None)
        self._thread.join(timeout=2.0)
