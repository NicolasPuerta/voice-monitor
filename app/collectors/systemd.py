"""Recolector de estado y servicios de systemd mediante D-Bus (MR 16).

Permite observar servicios, descripciones, estado de activación y fallos,
con caché de metadatos para evitar llamadas repetidas a ListUnits y degradación
elegante si systemd o D-Bus no están disponibles.
"""

from datetime import datetime, timezone
import logging
import time
from typing import Any

from app.collectors.base import Collector
from app.collectors.health import SourceHealthManager
from app.domain.systemd import ServiceState, SystemdSnapshot, UnitSnapshot

logger = logging.getLogger(__name__)


class SystemdCollector(Collector[SystemdSnapshot | None]):
    """Recolector de unidades y servicios de systemd vía D-Bus con caché."""

    def __init__(
        self,
        health_manager: SourceHealthManager | None = None,
        dbus_client: Any = None,
        cache_ttl_s: float = 60.0,
    ) -> None:
        self.health_manager = health_manager or SourceHealthManager()
        self.dbus_client = dbus_client
        self.cache_ttl_s = cache_ttl_s

        self._units_cache: dict[str, UnitSnapshot] = {}
        self._last_full_refresh: float = 0.0

    @property
    def name(self) -> str:
        """Nombre corto del collector."""
        return "systemd"

    @staticmethod
    def _get_default_dbus_client() -> Any | None:
        """Intenta inicializar el cliente D-Bus hacia systemd si está disponible."""
        try:
            import dbus  # type: ignore[import-not-found]

            bus = dbus.SystemBus()
            systemd1 = bus.get_object(
                "org.freedesktop.systemd1", "/org/freedesktop/systemd1"
            )
            return dbus.Interface(systemd1, "org.freedesktop.systemd1.Manager")
        except Exception:
            return None

    def collect(self) -> SystemdSnapshot | None:
        """Recolecta el estado de unidades de systemd respetando la caché."""
        now = datetime.now(timezone.utc)

        try:
            client = self.dbus_client
            if client is None:
                client = self._get_default_dbus_client()
                self.dbus_client = client

            if client is None:
                reason = "D-Bus / systemd no disponible en este sistema."
                logger.debug(reason)
                self.health_manager.record_failure("systemd", reason=reason)
                return None

            return self._collect_via_dbus(client, now)

        except Exception as exc:
            reason = f"Error comunicando con systemd vía D-Bus: {exc}"
            logger.debug(reason)
            self.health_manager.record_failure("systemd", reason=reason)
            return None

    def _collect_via_dbus(self, client: Any, now: datetime) -> SystemdSnapshot:
        """Consulta systemd a través del cliente D-Bus."""
        now_mono = time.monotonic()
        is_cache_valid = (
            bool(self._units_cache)
            and (now_mono - self._last_full_refresh) < self.cache_ttl_s
        )

        if not is_cache_valid:
            # Llamada completa ListUnits a través de D-Bus
            raw_units = client.ListUnits()
            new_cache: dict[str, UnitSnapshot] = {}
            for item in raw_units:
                # Formato standard D-Bus de systemd ListUnits:
                # (name, description, load_state, active_state, sub_state, ...)
                name = str(item[0])
                desc = str(item[1]) if len(item) > 1 else ""
                load_st = str(item[2]) if len(item) > 2 else "loaded"
                active_st_str = str(item[3]).lower() if len(item) > 3 else "unknown"
                sub_st = str(item[4]) if len(item) > 4 else ""

                try:
                    active_st = ServiceState(active_st_str)
                except ValueError:
                    active_st = ServiceState.UNKNOWN

                unit_type = "service" if name.endswith(".service") else "other"
                new_cache[name] = UnitSnapshot(
                    name=name,
                    description=desc,
                    load_state=load_st,
                    active_state=active_st,
                    sub_state=sub_st,
                    unit_type=unit_type,
                )

            self._units_cache = new_cache
            self._last_full_refresh = now_mono
        else:
            # En ticks intermedios: evitar ListUnits completo, consultar unidades fallidas
            if hasattr(client, "ListUnitsFiltered"):
                failed_raw = client.ListUnitsFiltered(["failed"])
                failed_names = {str(item[0]) for item in failed_raw}
                for name, unit in self._units_cache.items():
                    if name in failed_names:
                        object.__setattr__(unit, "active_state", ServiceState.FAILED)
                        object.__setattr__(unit, "sub_state", "failed")
                    elif unit.active_state == ServiceState.FAILED:
                        object.__setattr__(unit, "active_state", ServiceState.ACTIVE)
                        object.__setattr__(unit, "sub_state", "running")

        self.health_manager.record_success("systemd")
        return self._build_snapshot(now)

    def _build_snapshot(self, now: datetime) -> SystemdSnapshot:
        """Construye el snapshot inmutable a partir de la caché de unidades."""
        services = tuple(
            u for u in self._units_cache.values() if u.unit_type == "service"
        )
        failed = tuple(u for u in self._units_cache.values() if u.is_failed)
        active = sum(
            1
            for u in self._units_cache.values()
            if u.active_state == ServiceState.ACTIVE
        )

        return SystemdSnapshot(
            collected_at=now,
            units_total=len(self._units_cache),
            units_active=active,
            units_failed=len(failed),
            failed_units=failed,
            services=services,
        )
