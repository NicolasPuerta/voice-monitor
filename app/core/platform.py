"""Detector de plataforma, capacidades del sistema operativo y diagnósticos (MR 17).

Permite identificar Ubuntu, Debian y WSL, verificando la presencia de:
- systemd (sistema y usuario);
- D-Bus (sistema y sesión);
- journald;
- subsistema de audio (PipeWire, PulseAudio, WSLg, ALSA);
- métricas de presión PSI y energía/batería.
"""

import os
from pathlib import Path
import sys

from app.domain.platform import AudioBackendType, DistroInfo, PlatformCapabilities


class PlatformDetector:
    """Inspecciona el entorno y construye una instantánea de capacidades."""

    def __init__(
        self,
        proc_root: Path = Path("/proc"),
        sys_root: Path = Path("/sys"),
        etc_root: Path = Path("/etc"),
        run_root: Path = Path("/run"),
        uid: int | None = None,
    ) -> None:
        self.proc_root = proc_root
        self.sys_root = sys_root
        self.etc_root = etc_root
        self.run_root = run_root
        self.uid = uid

    def detect(self) -> PlatformCapabilities:
        """Realiza el escaneo completo de capacidades del entorno."""
        is_linux = sys.platform.startswith("linux") or self.proc_root.exists()
        is_wsl, wsl_ver = self._detect_wsl()
        distro = self._detect_distro()

        if self.uid is not None:
            uid = self.uid
        elif hasattr(os, "getuid"):
            uid = os.getuid()
        else:
            uid = 1000

        has_systemd = (self.run_root / "systemd" / "system").is_dir()
        has_user_systemd = has_systemd and (
            (self.run_root / "user" / str(uid) / "systemd" / "private").exists()
            or bool(os.environ.get("XDG_RUNTIME_DIR"))
        )

        has_dbus = (
            bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
            or (self.run_root / "user" / str(uid) / "bus").exists()
            or (self.run_root / "dbus" / "system_bus_socket").exists()
        )

        has_journald = (
            (self.run_root / "systemd" / "journal" / "socket").exists()
            or (self.run_root / "log" / "journal").exists()
            or (self.etc_root.parent / "var" / "log" / "journal").exists()
        )

        audio_backend = self._detect_audio_backend(uid)
        has_audio = audio_backend not in (
            AudioBackendType.NONE,
            AudioBackendType.UNKNOWN,
        )

        has_psi = (self.proc_root / "pressure" / "cpu").exists()
        has_battery = self._detect_battery()

        warnings = self._generate_warnings(
            is_wsl=is_wsl,
            wsl_version=wsl_ver,
            has_systemd=has_systemd,
            has_user_systemd=has_user_systemd,
            has_audio=has_audio,
            audio_backend=audio_backend,
            has_journald=has_journald,
            has_psi=has_psi,
        )

        return PlatformCapabilities(
            is_linux=is_linux,
            is_wsl=is_wsl,
            wsl_version=wsl_ver,
            distro=distro,
            has_systemd=has_systemd,
            has_user_systemd=has_user_systemd,
            has_dbus=has_dbus,
            has_journald=has_journald,
            has_audio=has_audio,
            audio_backend=audio_backend,
            has_psi=has_psi,
            has_battery=has_battery,
            warnings=tuple(warnings),
        )

    def _detect_wsl(self) -> tuple[bool, int | None]:
        """Determina si la ejecución ocurre bajo WSL y su versión (1 o 2)."""
        if "WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ:
            version_file = self.proc_root / "version"
            if version_file.is_file():
                try:
                    content = version_file.read_text(
                        encoding="utf-8", errors="ignore"
                    ).lower()
                    if "wsl2" in content or "microsoft-standard" in content:
                        return True, 2
                except Exception:
                    pass
            has_interop = (
                self.proc_root / "sys" / "fs" / "binfmt_misc"
            ).exists()
            return True, 2 if has_interop else 1

        version_file = self.proc_root / "version"
        if version_file.is_file():
            try:
                content = version_file.read_text(
                    encoding="utf-8", errors="ignore"
                ).lower()
                if "microsoft" in content or "wsl" in content:
                    is_v2 = "wsl2" in content or "microsoft-standard" in content
                    return True, 2 if is_v2 else 1
            except Exception:
                pass

        return False, None

    def _detect_distro(self) -> DistroInfo:
        """Lee y parsea la información de la distribución en /etc/os-release."""
        os_release = self.etc_root / "os-release"
        if not os_release.is_file():
            # Intentar /usr/lib/os-release si no está en /etc
            os_release = self.etc_root.parent / "usr" / "lib" / "os-release"

        data: dict[str, str] = {}
        if os_release.is_file():
            try:
                lines = os_release.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines()
                for line in lines:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        data[k.strip()] = v.strip().strip('"').strip("'")
            except Exception:
                pass

        distro_id = data.get("ID", "linux").lower()
        name = data.get("NAME", "Linux")
        version_id = data.get("VERSION_ID", "")
        pretty = data.get("PRETTY_NAME", f"{name} {version_id}".strip())

        return DistroInfo(
            id=distro_id,
            name=name,
            version_id=version_id,
            pretty_name=pretty,
        )

    def _detect_audio_backend(self, uid: int) -> AudioBackendType:
        """Determina el subsistema de audio presente en el sistema."""
        pulse_srv = os.environ.get("PULSE_SERVER", "").lower()
        wslg_pulse = Path("/mnt/wslg/runtime-dir/pulse/native")
        if wslg_pulse.exists() or "wslg" in pulse_srv:
            return AudioBackendType.WSLG

        pipewire_sock = self.run_root / "user" / str(uid) / "pipewire-0"
        if pipewire_sock.exists():
            return AudioBackendType.PIPEWIRE

        pulse_sock = self.run_root / "user" / str(uid) / "pulse" / "native"
        if pulse_sock.exists() or pulse_srv:
            return AudioBackendType.PULSEAUDIO

        snd_dir = Path("/dev/snd")
        if snd_dir.is_dir() and any(snd_dir.iterdir()):
            return AudioBackendType.ALSA

        return AudioBackendType.NONE

    def _detect_battery(self) -> bool:
        """Determina si existen baterías físicas reportadas por el kernel."""
        power_dir = self.sys_root / "class" / "power_supply"
        if not power_dir.is_dir():
            return False

        try:
            for entry in power_dir.iterdir():
                type_file = entry / "type"
                if type_file.is_file():
                    content = type_file.read_text(
                        encoding="utf-8", errors="ignore"
                    ).strip()
                    if content.lower() == "battery":
                        return True
        except Exception:
            pass

        return False

    @staticmethod
    def _generate_warnings(
        *,
        is_wsl: bool,
        wsl_version: int | None,
        has_systemd: bool,
        has_user_systemd: bool,
        has_audio: bool,
        audio_backend: AudioBackendType,
        has_journald: bool,
        has_psi: bool,
    ) -> list[str]:
        """Genera advertencias orientativas basadas en evidencias de la plataforma."""
        warnings: list[str] = []

        if is_wsl:
            if not has_systemd:
                warnings.append(
                    "WSL detectado sin systemd activo. Para habilitar servicios de "
                    "usuario, agregue '[boot]\\nsystemd=true' en /etc/wsl.conf y "
                    "ejecute 'wsl --shutdown'."
                )
            if not has_audio:
                warnings.append(
                    "Audio no detectado en WSL. Requiere WSLg (Windows 11) o un "
                    "servidor PulseAudio en Windows para reproducir voz. Use "
                    "--no-audio en modo texto."
                )
            warnings.append(
                "WSL no expone métricas de batería física ni control de energía hardware."
            )
        else:
            if not has_systemd:
                warnings.append(
                    "systemd no está activo como PID 1. El servicio de usuario no "
                    "estará disponible mediante systemctl --user."
                )
            elif not has_user_systemd:
                warnings.append(
                    "systemd de usuario (user manager) no parece estar activo en la "
                    "sesión. Verifique que dbus-user-session esté instalado."
                )
            if not has_audio:
                warnings.append(
                    "No se detectó servidor de audio (PipeWire, PulseAudio o ALSA). "
                    "La narración por voz estará deshabilitada (modo --no-audio)."
                )

        if not has_journald:
            warnings.append(
                "journald no está accesible o no expone socket en /run/systemd/journal. "
                "El recolector de journald permanecerá degradado."
            )

        if not has_psi:
            warnings.append(
                "El kernel no expone Pressure Stall Information (/proc/pressure). "
                "La detección de presión de memoria/disco estará degradada."
            )

        return warnings
