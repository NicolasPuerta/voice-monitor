"""Recolector incremental de eventos de journald (MR 16).

Permite observar de forma incremental (mediante cursor) eventos críticos:
OOM Killer, caídas de servicios y errores del sistema, con degradación elegante
si journald no está disponible en el entorno.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Callable

from app.collectors.base import Collector
from app.collectors.health import SourceHealthManager
from app.domain.journald import (
    JournalEntry,
    JournaldEventType,
    JournaldSnapshot,
)

logger = logging.getLogger(__name__)


class JournaldCollector(Collector[JournaldSnapshot | None]):
    """Recolector de bitácoras de journald con seguimiento incremental por cursor."""

    def __init__(
        self,
        health_manager: SourceHealthManager | None = None,
        reader: Any = None,
        entry_source: (
            Callable[[str | None, int], list[dict[str, Any]]] | None
        ) = None,
        batch_limit: int = 100,
    ) -> None:
        self.health_manager = health_manager or SourceHealthManager()
        self.reader = reader
        self.entry_source = entry_source
        self.batch_limit = batch_limit

        self._cursor: str | None = None
        self._initialized: bool = False

    @property
    def name(self) -> str:
        """Nombre corto del collector."""
        return "journald"

    @staticmethod
    def _get_default_reader() -> Any | None:
        """Intenta inicializar el lector de systemd.journal si está disponible."""
        try:
            from systemd import journal  # type: ignore[import-not-found]

            return journal.Reader()
        except Exception:
            return None

    def collect(self) -> JournaldSnapshot | None:
        """Lee incrementalmente nuevas entradas desde el último cursor."""
        now = datetime.now(timezone.utc)

        try:
            if self.entry_source is not None:
                return self._collect_via_entry_source(now)

            reader = self.reader
            if reader is None:
                reader = self._get_default_reader()
                self.reader = reader

            if reader is None:
                reason = "systemd.journal no está disponible en este sistema."
                logger.debug(reason)
                self.health_manager.record_failure("journald", reason=reason)
                return None

            return self._collect_via_reader(reader, now)

        except Exception as exc:
            reason = f"Error leyendo eventos de journald: {exc}"
            logger.debug(reason)
            self.health_manager.record_failure("journald", reason=reason)
            return None

    def _collect_via_entry_source(self, now: datetime) -> JournaldSnapshot:
        """Consume eventos a través de un entry_source inyectado."""
        if not self._initialized:
            # En la primera recolección, obtener cursor inicial sin procesar historial
            if hasattr(self.entry_source, "get_initial_cursor"):
                init_cursor_fn = getattr(self.entry_source, "get_initial_cursor")
                self._cursor = str(init_cursor_fn())
            self._initialized = True
            self.health_manager.record_success("journald")
            return JournaldSnapshot(
                collected_at=now,
                cursor=self._cursor,
                total_new_entries=0,
            )

        assert self.entry_source is not None
        raw_items = self.entry_source(self._cursor, self.batch_limit)
        entries: list[JournalEntry] = []
        new_cursor = self._cursor

        for item in raw_items:
            entry = self._parse_entry_dict(item, now)
            entries.append(entry)
            if entry.cursor:
                new_cursor = entry.cursor

        if new_cursor:
            self._cursor = new_cursor

        self.health_manager.record_success("journald")
        return self._build_snapshot(now, entries)

    def _collect_via_reader(self, reader: Any, now: datetime) -> JournaldSnapshot:
        """Consume eventos utilizando una instancia de systemd.journal.Reader."""
        entries: list[JournalEntry] = []
        new_cursor = self._cursor

        # Si no se ha inicializado, posicionar al final (tail) para no leer logs pasados
        if not self._initialized:
            if hasattr(reader, "seek_tail"):
                reader.seek_tail()
                if hasattr(reader, "get_previous"):
                    prev = reader.get_previous()
                    if prev and isinstance(prev, dict) and "__CURSOR" in prev:
                        self._cursor = prev["__CURSOR"]
            self._initialized = True
            self.health_manager.record_success("journald")
            return JournaldSnapshot(
                collected_at=now,
                cursor=self._cursor,
                total_new_entries=0,
            )

        if self._cursor and hasattr(reader, "seek_cursor"):
            reader.seek_cursor(self._cursor)

        count = 0
        while count < self.batch_limit:
            item = reader.get_next() if hasattr(reader, "get_next") else None
            if not item:
                break
            entry = self._parse_entry_dict(item, now)
            entries.append(entry)
            if entry.cursor:
                new_cursor = entry.cursor
            count += 1

        if new_cursor:
            self._cursor = new_cursor

        self.health_manager.record_success("journald")
        return self._build_snapshot(now, entries)

    def _parse_entry_dict(
        self, item: dict[str, Any], default_now: datetime
    ) -> JournalEntry:
        """Interpreta un diccionario de journald y clasifica el evento."""
        msg = str(item.get("MESSAGE", ""))
        cursor = item.get("__CURSOR")
        unit = item.get("_SYSTEMD_UNIT")
        identifier = item.get("SYSLOG_IDENTIFIER") or item.get("_COMM")

        prio = 6
        if "PRIORITY" in item:
            try:
                prio = int(item["PRIORITY"])
            except (ValueError, TypeError):
                prio = 6

        # Timestamp
        ts = default_now
        if "__REALTIME_TIMESTAMP" in item:
            try:
                usec = int(item["__REALTIME_TIMESTAMP"])
                ts = datetime.fromtimestamp(usec / 1_000_000, tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                ts = default_now

        # Clasificación del evento
        ev_type = self._classify_event(msg, prio, item)

        return JournalEntry(
            timestamp=ts,
            message=msg,
            priority=prio,
            cursor=cursor,
            unit=unit,
            identifier=identifier,
            event_type=ev_type,
            raw_fields=item,
        )

    @staticmethod
    def _classify_event(
        msg: str, priority: int, item: dict[str, Any]
    ) -> JournaldEventType:
        """Clasifica el mensaje buscando evidencias concretas de fallos."""
        msg_lower = msg.lower()

        # Evidencias de OOM Killer
        oom_patterns = (
            "out of memory: kill process",
            "invoked oom-killer",
            "killed process",
            "oom_reaper",
            "memory cgroup out of memory",
        )
        if any(pat in msg_lower for pat in oom_patterns):
            return JournaldEventType.OOM_KILL

        # Evidencias de caída de servicios
        service_fail_patterns = (
            "failed with result",
            "unit failed",
            "main process exited, code=exited",
            "failed to start",
            "crashed",
            "core dumped",
        )
        if any(pat in msg_lower for pat in service_fail_patterns):
            return JournaldEventType.SERVICE_FAILURE
        if item.get("JOB_RESULT") == "failed":
            return JournaldEventType.SERVICE_FAILURE

        # Errores generales del sistema
        if priority <= 3:
            return JournaldEventType.SYSTEM_ERROR
        if priority == 4:
            return JournaldEventType.WARNING

        return JournaldEventType.INFO

    @staticmethod
    def _build_snapshot(
        now: datetime, entries: list[JournalEntry]
    ) -> JournaldSnapshot:
        """Agrupa las entradas en un snapshot estructurado."""
        oom = tuple(e for e in entries if e.event_type == JournaldEventType.OOM_KILL)
        fails = tuple(
            e for e in entries if e.event_type == JournaldEventType.SERVICE_FAILURE
        )
        errors = tuple(
            e for e in entries if e.event_type == JournaldEventType.SYSTEM_ERROR
        )

        return JournaldSnapshot(
            collected_at=now,
            cursor=entries[-1].cursor if entries else None,
            total_new_entries=len(entries),
            oom_events=oom,
            service_failures=fails,
            error_events=errors,
        )
