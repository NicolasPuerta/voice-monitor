"""Pruebas del recolector incremental de journald (MR 16)."""

from typing import Any

from app.collectors.health import SourceHealthManager, SourceState
from app.collectors.journald import JournaldCollector
from app.domain.journald import JournaldEventType


class MockJournalReader:
    """Mock de systemd.journal.Reader para probar el protocolo del lector."""

    def __init__(self, entries: list[dict[str, Any]] | None = None) -> None:
        self.entries = list(entries or [])
        self._index = 0
        self.tail_called = False
        self.seek_cursor_called_with: str | None = None

    def seek_tail(self) -> None:
        self.tail_called = True

    def get_previous(self) -> dict[str, Any] | None:
        if self.entries:
            return self.entries[-1]
        return None

    def seek_cursor(self, cursor: str) -> None:
        self.seek_cursor_called_with = cursor

    def get_next(self) -> dict[str, Any] | None:
        if self._index < len(self.entries):
            item = self.entries[self._index]
            self._index += 1
            return item
        return None


def test_journald_initial_cursor_seeding() -> None:
    """Verifica que el inicio de journald posicione cursor sin procesar historial."""
    historical_entry = {
        "MESSAGE": "Old boot log",
        "__CURSOR": "s=historical_cursor_123",
        "PRIORITY": "6",
    }
    reader = MockJournalReader(entries=[historical_entry])
    health = SourceHealthManager()
    collector = JournaldCollector(health_manager=health, reader=reader)

    snap = collector.collect()
    assert snap is not None
    assert snap.total_new_entries == 0
    assert snap.cursor == "s=historical_cursor_123"
    assert reader.tail_called
    assert health.is_healthy("journald")


def test_journald_incremental_collection_via_entry_source() -> None:
    """Verifica la lectura incremental mediante cursor usando entry_source."""
    history = [
        {"MESSAGE": "Event 1", "__CURSOR": "c1", "PRIORITY": "6"},
        {"MESSAGE": "Event 2", "__CURSOR": "c2", "PRIORITY": "6"},
        {"MESSAGE": "Event 3", "__CURSOR": "c3", "PRIORITY": "6"},
    ]

    def mock_entry_source(
        cursor: str | None, batch_limit: int
    ) -> list[dict[str, Any]]:
        if cursor is None:
            return history[:2]
        if cursor == "c2":
            return history[2:]
        return []

    collector = JournaldCollector(entry_source=mock_entry_source)

    # 1. Init: seeds cursor
    snap0 = collector.collect()
    assert snap0 is not None
    assert snap0.total_new_entries == 0

    # 2. Tick 1: reads first batch
    snap1 = collector.collect()
    assert snap1 is not None
    assert snap1.total_new_entries == 2
    assert snap1.cursor == "c2"

    # 3. Tick 2: reads next incremental batch
    snap2 = collector.collect()
    assert snap2 is not None
    assert snap2.total_new_entries == 1
    assert snap2.cursor == "c3"

    # 4. Tick 3: no new entries
    snap3 = collector.collect()
    assert snap3 is not None
    assert snap3.total_new_entries == 0


def test_journald_event_classification() -> None:
    """Verifica la clasificación precisa de eventos OOM, caídas y errores."""
    entries = [
        {
            "MESSAGE": "kernel: Out of memory: Kill process 5678 (mysqld) score 850",
            "PRIORITY": "3",
            "__CURSOR": "c_oom",
        },
        {
            "MESSAGE": "mysqld.service: Main process exited, code=exited, status=1",
            "_SYSTEMD_UNIT": "mysqld.service",
            "PRIORITY": "3",
            "__CURSOR": "c_fail",
        },
        {
            "MESSAGE": "Disk I/O failure on device /dev/sdb",
            "PRIORITY": "2",
            "__CURSOR": "c_err",
        },
        {
            "MESSAGE": "High temperature warning on sensor 0",
            "PRIORITY": "4",
            "__CURSOR": "c_warn",
        },
        {
            "MESSAGE": "User logged in",
            "PRIORITY": "6",
            "__CURSOR": "c_info",
        },
    ]

    def source(cursor: str | None, limit: int) -> list[dict[str, Any]]:
        return entries

    collector = JournaldCollector(entry_source=source)
    collector._initialized = True  # bypass init tick

    snap = collector.collect()
    assert snap is not None
    assert snap.total_new_entries == 5
    assert len(snap.oom_events) == 1
    assert snap.oom_events[0].event_type == JournaldEventType.OOM_KILL
    assert len(snap.service_failures) == 1
    assert snap.service_failures[0].event_type == JournaldEventType.SERVICE_FAILURE
    assert len(snap.error_events) == 1
    assert snap.error_events[0].event_type == JournaldEventType.SYSTEM_ERROR


def test_journald_via_reader_mock() -> None:
    """Verifica la lectura a través de la interfaz Reader."""
    logs = [
        {
            "MESSAGE": "systemd: unit failed",
            "PRIORITY": "3",
            "__CURSOR": "r1",
            "__REALTIME_TIMESTAMP": "1767225600000000",
        }
    ]
    reader = MockJournalReader(entries=logs)
    collector = JournaldCollector(reader=reader)
    collector._initialized = True
    collector._cursor = "r0"

    snap = collector.collect()
    assert snap is not None
    assert snap.total_new_entries == 1
    assert reader.seek_cursor_called_with == "r0"
    assert snap.cursor == "r1"


def test_journald_degraded_when_unavailable() -> None:
    """Verifica degradación elegante cuando journald no existe en el sistema."""
    health = SourceHealthManager()
    collector = JournaldCollector(health_manager=health, reader=None, entry_source=None)
    collector._get_default_reader = staticmethod(lambda: None)  # type: ignore

    snap1 = collector.collect()
    assert snap1 is None
    assert health.get_consecutive_failures("journald") == 1

    snap2 = collector.collect()
    assert snap2 is None
    assert health.get_state("journald") == SourceState.DEGRADED
    assert not health.is_healthy("journald")


def test_journald_handles_permission_error_gracefully() -> None:
    """Verifica que una falla de permisos se gestione con degradación sin abortar."""
    health = SourceHealthManager()

    class DeniedReader:
        def seek_tail(self) -> None:
            raise PermissionError("Access denied to /var/log/journal")

    collector = JournaldCollector(health_manager=health, reader=DeniedReader())

    snap1 = collector.collect()
    assert snap1 is None
    assert health.get_consecutive_failures("journald") == 1
    assert "denied" in health.get_reason("journald")

    snap2 = collector.collect()
    assert snap2 is None
    assert health.get_state("journald") == SourceState.DEGRADED
