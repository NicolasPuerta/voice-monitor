"""Pruebas para el detector de plataforma y capacidades PlatformDetector (MR 17)."""

from pathlib import Path
from unittest.mock import patch

from app.core.platform import PlatformDetector
from app.domain.platform import AudioBackendType


def test_detect_native_ubuntu_22_04(tmp_path: Path) -> None:
    """Verifica detección de Ubuntu 22.04 nativo con todas las capacidades activas."""
    proc = tmp_path / "proc"
    sys_dir = tmp_path / "sys"
    etc = tmp_path / "etc"
    run = tmp_path / "run"

    # 1. os-release
    etc.mkdir(parents=True)
    (etc / "os-release").write_text(
        'NAME="Ubuntu"\nVERSION="22.04.4 LTS (Jammy Jellyfish)"\nID=ubuntu\n'
        'VERSION_ID="22.04"\nPRETTY_NAME="Ubuntu 22.04.4 LTS"\n',
        encoding="utf-8",
    )

    # 2. proc/version (kernel estándar de Ubuntu)
    proc.mkdir(parents=True)
    (proc / "version").write_text(
        "Linux version 5.15.0-105-generic (buildd@lcy02-amd64-001) "
        "(gcc (Ubuntu 11.4.0-1ubuntu1~22.04) 11.4.0) #115-Ubuntu SMP",
        encoding="utf-8",
    )

    # 3. systemd y user-systemd
    (run / "systemd" / "system").mkdir(parents=True)
    (run / "user" / "1000" / "systemd").mkdir(parents=True)
    (run / "user" / "1000" / "systemd" / "private").touch()

    # 4. D-Bus
    (run / "user" / "1000" / "bus").touch()

    # 5. journald
    (run / "systemd" / "journal").mkdir(parents=True)
    (run / "systemd" / "journal" / "socket").touch()

    # 6. PipeWire audio
    (run / "user" / "1000" / "pipewire-0").touch()

    # 7. PSI
    (proc / "pressure").mkdir(parents=True)
    (proc / "pressure" / "cpu").write_text("some avg10=0.00\n", encoding="utf-8")

    # 8. Batería
    bat = sys_dir / "class" / "power_supply" / "BAT0"
    bat.mkdir(parents=True)
    (bat / "type").write_text("Battery\n", encoding="utf-8")

    detector = PlatformDetector(
        proc_root=proc,
        sys_root=sys_dir,
        etc_root=etc,
        run_root=run,
        uid=1000,
    )

    caps = detector.detect()

    assert caps.is_linux is True
    assert caps.is_wsl is False
    assert caps.wsl_version is None
    assert caps.distro.id == "ubuntu"
    assert caps.distro.version_id == "22.04"
    assert "Ubuntu 22.04" in caps.distro.pretty_name
    assert caps.has_systemd is True
    assert caps.has_user_systemd is True
    assert caps.has_dbus is True
    assert caps.has_journald is True
    assert caps.audio_backend == AudioBackendType.PIPEWIRE
    assert caps.has_audio is True
    assert caps.has_psi is True
    assert caps.has_battery is True
    assert len(caps.warnings) == 0


def test_detect_native_debian_12(tmp_path: Path) -> None:
    """Verifica detección de Debian 12 (Bookworm) con PulseAudio."""
    proc = tmp_path / "proc"
    sys_dir = tmp_path / "sys"
    etc = tmp_path / "etc"
    run = tmp_path / "run"

    etc.mkdir(parents=True)
    (etc / "os-release").write_text(
        'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\nNAME="Debian GNU/Linux"\n'
        'VERSION_ID="12"\nVERSION="12 (bookworm)"\nID=debian\n',
        encoding="utf-8",
    )

    proc.mkdir(parents=True)
    (proc / "version").write_text(
        "Linux version 6.1.0-18-amd64 (debian-kernel@lists.debian.org) "
        "#1 SMP PREEMPT_DYNAMIC Debian 6.1.76-1 (2024-02-01)",
        encoding="utf-8",
    )

    (run / "systemd" / "system").mkdir(parents=True)
    (run / "user" / "1000" / "pulse").mkdir(parents=True)
    (run / "user" / "1000" / "pulse" / "native").touch()

    detector = PlatformDetector(
        proc_root=proc,
        sys_root=sys_dir,
        etc_root=etc,
        run_root=run,
        uid=1000,
    )

    caps = detector.detect()

    assert caps.distro.id == "debian"
    assert caps.distro.version_id == "12"
    assert caps.is_wsl is False
    assert caps.audio_backend == AudioBackendType.PULSEAUDIO


def test_detect_wsl2_with_systemd_and_wslg(tmp_path: Path) -> None:
    """Verifica detección de WSL2 con systemd y audio canalizado por WSLg."""
    proc = tmp_path / "proc"
    sys_dir = tmp_path / "sys"
    etc = tmp_path / "etc"
    run = tmp_path / "run"

    etc.mkdir(parents=True)
    (etc / "os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8")

    proc.mkdir(parents=True)
    (proc / "version").write_text(
        "Linux version 5.15.153.1-microsoft-standard-WSL2 (oe-user@oe-host) "
        "(x86_64-msft-linux-gcc (GCC) 11.2.0) #1 SMP Fri Mar 29 23:14:13 UTC 2024",
        encoding="utf-8",
    )

    (run / "systemd" / "system").mkdir(parents=True)

    detector = PlatformDetector(
        proc_root=proc,
        sys_root=sys_dir,
        etc_root=etc,
        run_root=run,
        uid=1000,
    )

    with patch.dict(
        "os.environ", {"PULSE_SERVER": "/mnt/wslg/runtime-dir/pulse/native"}
    ):
        caps = detector.detect()

    assert caps.is_wsl is True
    assert caps.wsl_version == 2
    assert caps.has_systemd is True
    assert caps.audio_backend == AudioBackendType.WSLG
    assert caps.has_audio is True
    # WSL siempre advierte sobre la ausencia de batería física
    assert any("batería física" in w for w in caps.warnings)


def test_detect_wsl1_missing_systemd_and_audio(tmp_path: Path) -> None:
    """Verifica advertencias generadas en WSL cuando faltan systemd y audio."""
    proc = tmp_path / "proc"
    sys_dir = tmp_path / "sys"
    etc = tmp_path / "etc"
    run = tmp_path / "run"

    etc.mkdir(parents=True)
    (etc / "os-release").write_text('ID=ubuntu\n', encoding="utf-8")

    proc.mkdir(parents=True)
    (proc / "version").write_text(
        "Linux version 4.4.0-19041-Microsoft (Microsoft@Microsoft.com) "
        "(gcc version 5.4.0) #1 SMP Fri Dec 06 14:06:00 PST 2019",
        encoding="utf-8",
    )

    detector = PlatformDetector(
        proc_root=proc,
        sys_root=sys_dir,
        etc_root=etc,
        run_root=run,
        uid=1000,
    )

    with patch.dict("os.environ", {}, clear=True):
        caps = detector.detect()

    assert caps.is_wsl is True
    assert caps.wsl_version == 1
    assert caps.has_systemd is False
    assert caps.has_audio is False

    # Debe advertir sobre /etc/wsl.conf para systemd y sobre audio
    assert any("/etc/wsl.conf" in w for w in caps.warnings)
    assert any("Audio no detectado en WSL" in w for w in caps.warnings)


def test_detect_missing_capabilities_generates_helpful_warnings(
    tmp_path: Path,
) -> None:
    """Verifica advertencias cuando journald y PSI no están disponibles."""
    proc = tmp_path / "proc"
    sys_dir = tmp_path / "sys"
    etc = tmp_path / "etc"
    run = tmp_path / "run"

    proc.mkdir(parents=True)
    (proc / "version").write_text("Linux version 5.4.0-generic\n", encoding="utf-8")

    detector = PlatformDetector(
        proc_root=proc,
        sys_root=sys_dir,
        etc_root=etc,
        run_root=run,
        uid=1000,
    )

    with patch.dict("os.environ", {}, clear=True):
        caps = detector.detect()

    assert caps.has_psi is False
    assert caps.has_journald is False
    assert any("journald" in w for w in caps.warnings)
    assert any("Pressure Stall Information" in w for w in caps.warnings)
