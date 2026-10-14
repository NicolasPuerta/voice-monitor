"""Modelos de dominio para detección de plataforma y capacidades (MR 17)."""

from enum import Enum

from app.domain.base import DomainModel


class AudioBackendType(str, Enum):
    """Tipo de subsistema de audio detectado."""

    PIPEWIRE = "pipewire"
    PULSEAUDIO = "pulseaudio"
    WSLG = "wslg"
    ALSA = "alsa"
    UNKNOWN = "unknown"
    NONE = "none"


class DistroInfo(DomainModel):
    """Información de la distribución del sistema operativo."""

    id: str = "linux"
    """Identificador canónico (ej. 'ubuntu', 'debian')."""

    name: str = "Linux"
    """Nombre descriptivo (ej. 'Ubuntu', 'Debian GNU/Linux')."""

    version_id: str = ""
    """Versión específica (ej. '22.04', '24.04', '12')."""

    pretty_name: str = "Linux"
    """Nombre completo con versión."""


class PlatformCapabilities(DomainModel):
    """Capacidades y subsistemas detectados en el entorno de ejecución."""

    is_linux: bool = True
    """Indica si el sistema operativo base es GNU/Linux."""

    is_wsl: bool = False
    """Indica si se ejecuta bajo Windows Subsystem for Linux (WSL)."""

    wsl_version: int | None = None
    """Versión detectada de WSL (1 o 2)."""

    distro: DistroInfo = DistroInfo()
    """Detalles de la distribución Linux detectada."""

    has_systemd: bool = False
    """Indica si systemd está activo como sistema de inicio."""

    has_user_systemd: bool = False
    """Indica si systemd a nivel de usuario (systemctl --user) está disponible."""

    has_dbus: bool = False
    """Indica si el bus D-Bus (sistema o sesión) se encuentra accesible."""

    has_journald: bool = False
    """Indica si el daemon de bitácoras journald está disponible y legible."""

    has_audio: bool = False
    """Indica si hay un subsistema de audio funcional detectado."""

    audio_backend: AudioBackendType = AudioBackendType.NONE
    """Subsistema de audio detectado."""

    has_psi: bool = False
    """Indica si el kernel expone métricas de presión PSI (/proc/pressure)."""

    has_battery: bool = False
    """Indica si el sistema expone información de batería física."""

    warnings: tuple[str, ...] = ()
    """Advertencias o limitaciones detectadas para el entorno actual."""
