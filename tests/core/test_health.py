"""Pruebas para SourceHealthManager y degradación elegante."""

from app.collectors.health import SourceHealthManager, SourceState


def test_health_manager_initial_state() -> None:
    mgr = SourceHealthManager()
    assert mgr.get_state("psi") == SourceState.OK
    assert mgr.is_healthy("psi")
    assert mgr.can_attempt("psi")
    assert mgr.get_consecutive_failures("psi") == 0


def test_health_manager_failure_transitions() -> None:
    mgr = SourceHealthManager(base_backoff_s=1.0, max_backoff_s=10.0)

    # 1 fallo: aún OK
    mgr.record_failure("gemini", reason="Timeout", now=100.0)
    assert mgr.get_state("gemini") == SourceState.OK
    assert mgr.get_consecutive_failures("gemini") == 1

    # 2 fallos: pasa a DEGRADED
    mgr.record_failure("gemini", reason="503 Service Unavailable", now=101.0)
    assert mgr.get_state("gemini") == SourceState.DEGRADED
    assert not mgr.is_healthy("gemini")
    assert mgr.get_reason("gemini") == "503 Service Unavailable"

    # 5 fallos: pasa a DISABLED
    mgr.record_failure("gemini", reason="Quota Exceeded", now=102.0)
    mgr.record_failure("gemini", reason="Quota Exceeded", now=103.0)
    mgr.record_failure("gemini", reason="Quota Exceeded", now=104.0)
    assert mgr.get_state("gemini") == SourceState.DISABLED
    assert mgr.get_consecutive_failures("gemini") == 5


def test_health_manager_backoff_and_recovery() -> None:
    mgr = SourceHealthManager(base_backoff_s=2.0, max_backoff_s=8.0)

    # Provocar estado DEGRADED
    mgr.record_failure("audio", reason="Sink error", now=100.0)
    mgr.record_failure("audio", reason="Sink error", now=100.0)
    assert mgr.get_state("audio") == SourceState.DEGRADED

    # Inmediatamente después del fallo no se puede intentar
    assert not mgr.can_attempt("audio", now=101.0)

    # Después de pasar la ventana de backoff (8.0s), se permite prueba de recuperación
    assert mgr.can_attempt("audio", now=110.0)

    # Si la prueba tiene éxito, se recupera el estado a OK
    mgr.record_success("audio", now=111.0)
    assert mgr.get_state("audio") == SourceState.OK
    assert mgr.is_healthy("audio")
    assert mgr.get_consecutive_failures("audio") == 0


def test_independent_sources() -> None:
    """Verifica que el fallo en una fuente no afecte a las demás."""
    mgr = SourceHealthManager()

    mgr.record_failure("psi", reason="Missing /proc/pressure", threshold_degraded=1)
    mgr.record_success("sqlite")
    mgr.record_success("gemini")

    assert mgr.get_state("psi") == SourceState.DEGRADED
    assert mgr.get_state("sqlite") == SourceState.OK
    assert mgr.get_state("gemini") == SourceState.OK
