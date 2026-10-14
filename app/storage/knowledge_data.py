"""Base de conocimiento versionada de procesos comunes de Linux (MR 18).

Provee descripciones verificables y objetivas para 200–300 procesos y demonios comunes
en entornos Linux (Ubuntu 22.04/24.04, Debian 12, GNOME, KDE, desarrollo, contenedores,
bases de datos y utilidades del sistema).
"""

import json
from pathlib import Path
from typing import Any

_JSON_PATH = Path(__file__).parent / "knowledge_data.json"


def _load_processes() -> list[dict[str, Any]]:
    if not _JSON_PATH.exists():
        return []
    with _JSON_PATH.open("r", encoding="utf-8") as f:
        data: list[dict[str, Any]] = json.load(f)
        return data


SEEDED_PROCESSES: list[dict[str, Any]] = _load_processes()


def get_seeded_knowledge() -> list[tuple[str, str, str, str, str, str, int]]:
    """Devuelve las entradas de la base de conocimiento en tuplas para SQLite."""
    return [
        (
            item["key"],
            item["short_text"],
            item["long_text"],
            item["category"],
            item["source"],
            item["confidence"],
            item["version"],
        )
        for item in SEEDED_PROCESSES
    ]
