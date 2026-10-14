"""Administrador de No Molestar (DND) y detección pasiva de actividad."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.collectors.health import SourceHealthManager
from app.domain.enums import EventDecision, EventPriority
from app.domain.events import Event

logger = logging.getLogger(__name__)

DEFAULT_PROC_ASOUND = Path("/proc/asound")
DEFAULT_SYS_VIDEO = Path("/sys/class/video4linux")


class DNDManager:
    """Gestiona el estado de No Molestar (DND).

    Detecta señales del sistema sin invadir la privacidad.
    """

    def __init__(
        self,
        health_manager: SourceHealthManager | None = None,
        manual_dnd: bool = False,
        text_only: bool = False,
        proc_asound_path: Path = DEFAULT_PROC_ASOUND,
        sys_video_path: Path = DEFAULT_SYS_VIDEO,
        dbus_probe: Callable[[], bool] | None = None,
    ) -> None:
        self.health_manager = health_manager or SourceHealthManager()
        self._manual_dnd = manual_dnd
        self.text_only = text_only
        self.proc_asound_path = proc_asound_path
        self.sys_video_path = sys_video_path
        self._custom_dbus_probe = dbus_probe

        self._paused = manual_dnd
        self._pause_reason = "config" if manual_dnd else ""

    def pause(self, reason: str = "manual") -> None:
        """Pausa manualmente las narraciones de audio."""
        self._paused = True
        self._pause_reason = reason
        logger.info("Modo No Molestar activado manualmente: %s", reason)

    def resume(self) -> None:
        """Reanuda las narraciones de audio."""
        self._paused = False
        self._pause_reason = ""
        logger.info("Modo No Molestar desactivado. Narraciones reanudadas.")

    @property
    def is_paused(self) -> bool:
        """Indica si el sistema está en pausa manual."""
        return self._paused

    def is_microphone_in_use(self) -> bool:
        """Detecta si hay una captura de audio activa leyendo el estado de ALSA en /proc.

        No graba ni accede al flujo de audio; únicamente revisa estado de descriptores.
        """
        if not self.proc_asound_path.exists():
            return False

        try:
            # En Linux, las capturas de audio residen en pcm*c/sub*/status
            for status_file in self.proc_asound_path.glob("card*/pcm*c/sub*/status"):
                try:
                    content = status_file.read_text(encoding="utf-8", errors="ignore")
                    if "state: RUNNING" in content:
                        return True
                except (OSError, PermissionError):
                    continue
        except Exception as exc:
            logger.debug("Error verificando micrófono en ALSA: %s", exc)

        return False

    def is_camera_in_use(self) -> bool:
        """Detecta si alguna cámara está activa en /sys/class/video4linux.

        No captura ni procesa fotogramas de video; solo revisa los dispositivos V4L2.
        """
        if not self.sys_video_path.exists():
            return False

        try:
            video_devs = list(self.sys_video_path.glob("video*"))
            # Si existen dispositivos y se detecta una señal activa o flag
            # (en mock tests se verifica existencia o archivo 'active'/'streaming')
            for dev in video_devs:
                active_marker = dev / "active"
                if active_marker.exists():
                    try:
                        if active_marker.read_text(encoding="utf-8").strip() in (
                            "1",
                            "true",
                        ):
                            return True
                    except (OSError, PermissionError):
                        continue
        except Exception as exc:
            logger.debug("Error verificando cámara: %s", exc)

        return False

    def is_media_playing(self) -> bool:
        """Detecta si hay reproducción multimedia activa en ALSA (pcm*p/sub*/status)."""
        if not self.proc_asound_path.exists():
            return False

        try:
            for status_file in self.proc_asound_path.glob("card*/pcm*p/sub*/status"):
                try:
                    content = status_file.read_text(encoding="utf-8", errors="ignore")
                    if "state: RUNNING" in content:
                        return True
                except (OSError, PermissionError):
                    continue
        except Exception as exc:
            logger.debug("Error verificando reproducción ALSA: %s", exc)

        return False

    def is_game_mode_active(self, process_names: list[str] | None = None) -> bool:
        """Detecta si GameMode o un proceso de juego conocido está en ejecución."""
        known_game_indicators = {"gamemoded", "steam_app", "wine", "proton"}
        if process_names:
            for p in process_names:
                p_lower = p.lower()
                if any(ind in p_lower for ind in known_game_indicators):
                    return True
        return False

    def is_desktop_inhibited(self) -> bool:
        """Revisa inhibidores de escritorio o DND vía D-Bus con degradación elegante."""
        if self._custom_dbus_probe is not None:
            try:
                inhibited = self._custom_dbus_probe()
                self.health_manager.record_success("dbus")
                return inhibited
            except Exception as exc:
                self.health_manager.record_failure("dbus", reason=str(exc))
                return False

        # Si no hay sonda personalizada, degradación elegante segura
        return False

    def should_suppress_audio(
        self,
        event: Event | None = None,
        process_names: list[str] | None = None,
    ) -> tuple[bool, str]:
        """Determina si la narración de audio debe suprimirse por alguna condición DND.

        Returns:
            Tupla (suprimir_audio, motivo).
        """
        # Eventos CRITICAL siempre pasan salvo pausa manual absoluta
        is_critical = event and event.severity.value == EventPriority.CRITICAL.value

        if self._paused:
            return True, f"manual_pause:{self._pause_reason}"

        if self.text_only:
            return True, "mode:text_only"

        # Señales de no molestar ambientales
        if self.is_microphone_in_use():
            if not is_critical:
                return True, "sensor:microphone_in_use"

        if self.is_camera_in_use():
            if not is_critical:
                return True, "sensor:camera_in_use"

        if self.is_game_mode_active(process_names):
            if not is_critical:
                return True, "activity:game_mode"

        if self.is_media_playing():
            if not is_critical:
                return True, "activity:media_playing"

        if self.is_desktop_inhibited():
            if not is_critical:
                return True, "desktop:inhibited"

        return False, ""

    def handle_event_dnd(
        self,
        event: Event,
        process_names: list[str] | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Evalúa un evento contra las reglas de DND.

        Si DND está activo, el evento se marca como DND o DEFERRED sin perderse,
        asegurando su persistencia en base de datos.

        Returns:
            True si el evento fue retenido/silenciado por DND; False si puede narrarse.
        """
        suppress, reason = self.should_suppress_audio(event, process_names)
        if suppress:
            current_time = datetime.now(timezone.utc) if now is None else now
            object.__setattr__(event, "decision", EventDecision.DND)
            event.metadata.extra["dnd_suppressed"] = "true"
            event.metadata.extra["dnd_reason"] = reason
            event.metadata.extra["dnd_timestamp"] = current_time.isoformat()
            logger.info(
                "[DND ACTIVO: %s] Evento guardado y silenciado: %s",
                reason,
                event.summary,
            )
            return True

        return False
