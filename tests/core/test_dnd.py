"""Pruebas para DNDManager y detección pasiva de actividad."""

from pathlib import Path
from datetime import datetime, timezone
from app.collectors.health import SourceHealthManager
from app.core.dnd import DNDManager
from app.domain.enums import EventDecision, EventSeverity, EventType
from app.domain.events import Event, EventMetadata

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_dnd_manual_pause_and_resume() -> None:
    mgr = DNDManager(manual_dnd=False)
    assert not mgr.is_paused

    mgr.pause(reason="reunión")
    assert mgr.is_paused
    suppress, reason = mgr.should_suppress_audio()
    assert suppress
    assert "reunión" in reason

    mgr.resume()
    assert not mgr.is_paused
    suppress, _ = mgr.should_suppress_audio()
    assert not suppress


def test_dnd_microphone_detection(tmp_path: Path) -> None:
    # Simular estructura de ALSA en /proc/asound
    card_pcm = tmp_path / "card0" / "pcm0c" / "sub0"
    card_pcm.mkdir(parents=True)
    status_file = card_pcm / "status"

    status_file.write_text("closed\n")
    mgr = DNDManager(proc_asound_path=tmp_path)
    assert not mgr.is_microphone_in_use()

    # Cambiar estado a RUNNING
    status_file.write_text("state: RUNNING\nowner_pid: 1234\n")
    assert mgr.is_microphone_in_use()

    suppress, reason = mgr.should_suppress_audio()
    assert suppress
    assert reason == "sensor:microphone_in_use"


def test_dnd_camera_detection(tmp_path: Path) -> None:
    # Simular /sys/class/video4linux
    video0 = tmp_path / "video0"
    video0.mkdir(parents=True)
    active_file = video0 / "active"

    active_file.write_text("0\n")
    mgr = DNDManager(sys_video_path=tmp_path)
    assert not mgr.is_camera_in_use()

    active_file.write_text("1\n")
    assert mgr.is_camera_in_use()

    suppress, reason = mgr.should_suppress_audio()
    assert suppress
    assert reason == "sensor:camera_in_use"


def test_dnd_game_mode() -> None:
    mgr = DNDManager()
    assert not mgr.is_game_mode_active(["bash", "firefox", "python"])
    assert mgr.is_game_mode_active(["bash", "gamemoded", "discord"])
    assert mgr.is_game_mode_active(["steam_app_12345"])


def test_dnd_desktop_inhibitor_and_dbus_degradation() -> None:
    health = SourceHealthManager()

    # 1. Sonda D-Bus exitosa
    mgr_ok = DNDManager(health_manager=health, dbus_probe=lambda: True)
    assert mgr_ok.is_desktop_inhibited()
    assert health.is_healthy("dbus")

    # 2. Sonda D-Bus con fallo (debe degradar sin romper la aplicación)
    def failing_probe() -> bool:
        raise ConnectionError("D-Bus daemon no disponible")

    mgr_fail = DNDManager(health_manager=health, dbus_probe=failing_probe)
    assert not mgr_fail.is_desktop_inhibited()
    assert not mgr_fail.is_desktop_inhibited()
    assert not health.is_healthy("dbus")
    assert health.get_consecutive_failures("dbus") == 2


def test_dnd_text_only_mode() -> None:
    mgr = DNDManager(text_only=True)
    suppress, reason = mgr.should_suppress_audio()
    assert suppress
    assert reason == "mode:text_only"


def test_dnd_handles_event_without_losing_it() -> None:
    mgr = DNDManager()
    mgr.pause("focus_time")

    event = Event(
        event_type=EventType.CPU_SPIKE,
        severity=EventSeverity.HIGH,
        summary="Pico de CPU",
        metadata=EventMetadata(),
    )

    handled = mgr.handle_event_dnd(event, now=NOW)
    assert handled
    assert event.decision == EventDecision.DND
    assert event.metadata.extra["dnd_suppressed"] == "true"
    assert "focus_time" in event.metadata.extra["dnd_reason"]


def test_dnd_allows_critical_events_through() -> None:
    mgr = DNDManager()
    # Simular sensor ocupado (ej. micrófono)
    mgr.is_microphone_in_use = lambda: True  # type: ignore[assignment]

    normal_event = Event(
        event_type=EventType.CPU_SPIKE,
        severity=EventSeverity.MEDIUM,
        summary="Carga normal",
    )
    assert mgr.should_suppress_audio(normal_event)[0] is True

    critical_event = Event(
        event_type=EventType.CPU_SPIKE,
        severity=EventSeverity.CRITICAL,
        summary="Presión crítica extrema",
    )
    # Evento crítico no es suprimido por señales de sensores
    assert mgr.should_suppress_audio(critical_event)[0] is False


def _running_playback(tmp_path: Path) -> None:
    card_pcm = tmp_path / "card0" / "pcm0p" / "sub0"
    card_pcm.mkdir(parents=True)
    (card_pcm / "status").write_text("state: RUNNING\nowner_pid: 1234\n")


def test_dnd_media_playing_detection(tmp_path: Path) -> None:
    _running_playback(tmp_path)
    mgr = DNDManager(proc_asound_path=tmp_path)

    assert mgr.is_media_playing()
    assert mgr.should_suppress_audio() == (True, "activity:media_playing")


def test_dnd_ignores_own_narration_playback(tmp_path: Path) -> None:
    """La propia voz del monitor no debe activar DND por multimedia."""
    _running_playback(tmp_path)
    now = [100.0]
    mgr = DNDManager(
        proc_asound_path=tmp_path, self_playback_grace_s=6.0, clock=lambda: now[0]
    )

    mgr.own_playback_started()
    assert not mgr.is_media_playing()
    assert mgr.should_suppress_audio() == (False, "")

    # PipeWire mantiene el PCM en RUNNING unos segundos tras terminar
    mgr.own_playback_finished()
    now[0] += 5.0
    assert not mgr.is_media_playing()

    # Pasada la ventana de gracia, un PCM activo vuelve a ser del usuario
    now[0] += 1.5
    assert mgr.is_media_playing()
    assert mgr.should_suppress_audio() == (True, "activity:media_playing")


def test_dnd_own_playback_does_not_hide_microphone(tmp_path: Path) -> None:
    capture = tmp_path / "card0" / "pcm0c" / "sub0"
    capture.mkdir(parents=True)
    (capture / "status").write_text("state: RUNNING\n")
    mgr = DNDManager(proc_asound_path=tmp_path)

    mgr.own_playback_started()
    assert mgr.should_suppress_audio() == (True, "sensor:microphone_in_use")
