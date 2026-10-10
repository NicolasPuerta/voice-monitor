"""Repositorios para persistir el modelo de dominio asncronamente."""

import json
import uuid
from datetime import datetime

from app.domain.events import Event
from app.domain.knowledge import ProcessKnowledge
from app.storage.db import BackgroundDatabase


class SessionRepository:
    def __init__(self, db: BackgroundDatabase) -> None:
        self.db = db

    def start_session(self, session_id: str, started_at: datetime) -> None:
        self.db.execute_async(
            "INSERT INTO sessions (id, started_at) VALUES (?, ?)",
            (session_id, started_at.isoformat()),
        )

    def end_session(self, session_id: str, ended_at: datetime) -> None:
        self.db.execute_async(
            "UPDATE sessions SET ended_at = ? WHERE id = ?",
            (ended_at.isoformat(), session_id),
        )


class EventRepository:
    def __init__(self, db: BackgroundDatabase) -> None:
        self.db = db

    def save_event(self, session_id: str, event: Event) -> None:
        score = event.score_result.score if event.score_result else None

        impact = novelty = anomaly = risk = relevance = rep_penalty = None
        if event.score_result and event.score_result.breakdown:
            b = event.score_result.breakdown
            impact = b.impact
            novelty = b.novelty
            anomaly = b.anomaly
            risk = b.risk
            relevance = b.relevance
            rep_penalty = b.repetition_penalty

        decision = event.decision.value if event.decision else None

        self.db.execute_async(
            """
            INSERT INTO events (
                id, session_id, event_type, severity, confidence, decision, 
                score, impact, novelty, anomaly, risk, relevance, repetition_penalty,
                detected_at, app_key, summary, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(event.id),
                session_id,
                event.event_type.value,
                event.severity.value,
                event.confidence.value,
                decision,
                score,
                impact,
                novelty,
                anomaly,
                risk,
                relevance,
                rep_penalty,
                event.detected_at.isoformat(),
                event.metadata.app_key,
                event.summary,
                json.dumps(event.metadata.extra),
            ),
        )


class KnowledgeRepository:
    def __init__(self, db: BackgroundDatabase) -> None:
        self.db = db

    def get_knowledge(self, app_key: str, name: str) -> ProcessKnowledge:
        # 1. Bsqueda por llave exacta
        rows = self.db.fetch_sync(
            "SELECT * FROM process_knowledge WHERE key = ?", (app_key,)
        )
        if rows:
            return self._row_to_model(rows[0])

        # 2. Heurstica para conocidos (ej. Python, Node, Java)
        if "python" in name.lower() or "cmd:python" in app_key:
            return ProcessKnowledge(
                key=app_key,
                short_text="Proceso de Python.",
                long_text="Script ejecutado mediante el intrprete Python. Su comportamiento depende del cdigo ejecutado.",
                category="development",
                source="heuristic",
                confidence="low",
            )
        elif "node" in name.lower() or "java" in name.lower():
            return ProcessKnowledge(
                key=app_key,
                short_text=f"Proceso de {name}.",
                long_text="Entorno de ejecucin detectado. Consumo variable segn la carga de trabajo.",
                category="development",
                source="heuristic",
                confidence="low",
            )

        # 3. Fallback genrico
        return ProcessKnowledge(
            key=app_key,
            short_text=f"Aplicacin desconocida: {name}.",
            long_text="Proceso detectado sin firma en la base de conocimientos.",
            category="unknown",
            source="unknown",
            confidence="low",
        )

    def _row_to_model(self, row: dict) -> ProcessKnowledge:
        return ProcessKnowledge(
            key=row["key"],
            short_text=row["short_text"],
            long_text=row["long_text"],
            category=row["category"],
            source=row["source"],
            confidence=row["confidence"],
            version=row["version"],
        )


class SourceHealthRepository:
    def __init__(self, db: BackgroundDatabase) -> None:
        self.db = db

    def save_health(
        self, session_id: str, source: str, state: str, reason: str, now: datetime
    ) -> None:
        self.db.execute_async(
            """
            INSERT INTO source_health (id, session_id, source, state, reason, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), session_id, source, state, reason, now.isoformat()),
        )
