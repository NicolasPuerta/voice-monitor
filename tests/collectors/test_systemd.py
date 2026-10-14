"""Pruebas del recolector de systemd mediante D-Bus (MR 16)."""

from typing import Any
import pytest

from app.collectors.health import SourceHealthManager, SourceState
from app.collectors.systemd import SystemdCollector
from app.domain.systemd import ServiceState


class MockDbusClient:
    """Cliente mock de D-Bus para simular respuestas de systemd."""

    def __init__(
        self,
        units: list[tuple[Any, ...]] | None = None,
        failed_units: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.units = units or []
        self.failed_units = failed_units or []
        self.list_units_calls = 0
        self.list_units_filtered_calls = 0

    def ListUnits(self) -> list[tuple[Any, ...]]:
        self.list_units_calls += 1
        return self.units

    def ListUnitsFiltered(self, states: list[str]) -> list[tuple[Any, ...]]:
        self.list_units_filtered_calls += 1
        return self.failed_units


def test_systemd_dbus_full_collection() -> None:
    """Verifica la recolección y parseo de unidades vía ListUnits de D-Bus."""
    raw_units = [
        (
            "nginx.service",
            "Nginx Web Server",
            "loaded",
            "active",
            "running",
            "",
            "/org/freedesktop/systemd1/unit/nginx_2eservice",
            0,
            "",
            "/",
        ),
        (
            "postgresql.service",
            "PostgreSQL Database",
            "loaded",
            "failed",
            "failed",
            "",
            "/org/freedesktop/systemd1/unit/postgresql_2eservice",
            0,
            "",
            "/",
        ),
        (
            "dev-sda1.device",
            "Root partition device",
            "loaded",
            "active",
            "plugged",
            "",
            "/org/freedesktop/systemd1/unit/dev_2dsda1_2edevice",
            0,
            "",
            "/",
        ),
    ]
    mock_client = MockDbusClient(units=raw_units)
    health = SourceHealthManager()
    collector = SystemdCollector(health_manager=health, dbus_client=mock_client)

    snap = collector.collect()
    assert snap is not None
    assert snap.units_total == 3
    assert snap.units_active == 2
    assert snap.units_failed == 1
    assert len(snap.services) == 2  # nginx y postgresql
    assert len(snap.failed_units) == 1
    assert snap.failed_units[0].name == "postgresql.service"
    assert snap.failed_units[0].description == "PostgreSQL Database"
    assert snap.failed_units[0].active_state == ServiceState.FAILED
    assert health.is_healthy("systemd")
    assert mock_client.list_units_calls == 1


def test_systemd_dbus_caching_and_interim_filtered_call() -> None:
    """Verifica que ticks dentro de la ventana de caché eviten llamar a ListUnits."""
    raw_units = [
        (
            "app.service",
            "My Application",
            "loaded",
            "active",
            "running",
        ),
    ]
    failed_units = [
        (
            "app.service",
            "My Application",
            "loaded",
            "failed",
            "failed",
        )
    ]
    mock_client = MockDbusClient(units=raw_units, failed_units=failed_units)
    collector = SystemdCollector(
        dbus_client=mock_client,
        cache_ttl_s=10.0,
    )

    # 1. Primera recolección: llamada completa a ListUnits
    snap1 = collector.collect()
    assert snap1 is not None
    assert mock_client.list_units_calls == 1
    assert mock_client.list_units_filtered_calls == 0
    assert snap1.units_failed == 0

    # 2. Segunda recolección inmediata: utiliza caché y sólo consulta unidades fallidas
    snap2 = collector.collect()
    assert snap2 is not None
    assert mock_client.list_units_calls == 1  # No se incrementó ListUnits
    assert mock_client.list_units_filtered_calls == 1  # Llamó a ListUnitsFiltered
    assert snap2.units_failed == 1
    assert snap2.failed_units[0].name == "app.service"


def test_systemd_dbus_cache_expiration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que tras expirar el TTL de caché se invoque ListUnits nuevamente."""
    raw_units = [("x.service", "X", "loaded", "active", "running")]
    mock_client = MockDbusClient(units=raw_units)
    collector = SystemdCollector(dbus_client=mock_client, cache_ttl_s=5.0)

    collector.collect()
    assert mock_client.list_units_calls == 1

    # Simular paso del tiempo mayor al TTL
    now_mono = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: now_mono[0])
    collector._last_full_refresh = 90.0  # 10s atrás (> 5s TTL)

    collector.collect()
    assert mock_client.list_units_calls == 2


def test_systemd_degraded_when_dbus_missing() -> None:
    """Verifica degradación a fallo cuando no existe cliente D-Bus disponible."""
    health = SourceHealthManager()
    collector = SystemdCollector(health_manager=health, dbus_client=None)

    # Forzar que _get_default_dbus_client devuelva None
    collector._get_default_dbus_client = staticmethod(lambda: None)  # type: ignore

    snap1 = collector.collect()
    assert snap1 is None
    assert health.get_consecutive_failures("systemd") == 1

    # Al segundo fallo consecutivo la fuente pasa a DEGRADED
    snap2 = collector.collect()
    assert snap2 is None
    assert health.get_state("systemd") == SourceState.DEGRADED
    assert not health.is_healthy("systemd")


def test_systemd_handles_dbus_exceptions_gracefully() -> None:
    """Verifica que una excepción de D-Bus no cause caída de la aplicación."""
    health = SourceHealthManager()

    class FailingClient:
        def ListUnits(self) -> None:
            raise PermissionError("Access to org.freedesktop.systemd1 denied")

    collector = SystemdCollector(
        health_manager=health, dbus_client=FailingClient()
    )

    snap1 = collector.collect()
    assert snap1 is None
    assert health.get_consecutive_failures("systemd") == 1
    assert "denied" in health.get_reason("systemd")

    snap2 = collector.collect()
    assert snap2 is None
    assert health.get_state("systemd") == SourceState.DEGRADED
    assert not health.is_healthy("systemd")
