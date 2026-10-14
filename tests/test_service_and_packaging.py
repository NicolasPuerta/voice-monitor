"""Pruebas de configuración del servicio systemd y empaquetado (MR 17)."""

from configparser import ConfigParser
from pathlib import Path
import re

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_systemd_unit_file_structure_and_security() -> None:
    """Valida las directivas de seguridad, logging y ciclo de vida en el unit file."""
    unit_file = ROOT_DIR / "packaging" / "systemd" / "voice-monitor.service"
    assert unit_file.is_file(), f"No se encontró el archivo de servicio en {unit_file}"

    # Cargar y parsear el archivo con ConfigParser permitiendo prefijos '-'
    content = unit_file.read_text(encoding="utf-8")
    parser = ConfigParser(interpolation=None, strict=False)
    # Evitar conversión de claves a minúsculas
    parser.optionxform = lambda option: option  # type: ignore
    parser.read_string(content)

    # 1. Secciones obligatorias
    assert parser.has_section("Unit")
    assert parser.has_section("Service")
    assert parser.has_section("Install")

    # 2. Target de usuario (default.target, no multi-user.target)
    assert parser.get("Install", "WantedBy") == "default.target"

    # 3. Reinicio controlado
    assert parser.get("Service", "Restart") == "on-failure"
    assert parser.get("Service", "RestartSec") == "5s"
    assert parser.get("Unit", "StartLimitIntervalSec") == "60s"
    assert parser.get("Unit", "StartLimitBurst") == "5"

    # 4. Logs a journald
    assert parser.get("Service", "StandardOutput") == "journal"
    assert parser.get("Service", "StandardError") == "journal"
    assert parser.get("Service", "SyslogIdentifier") == "voice-monitor"

    # 5. Seguridad y Mínimos Privilegios (Least Privilege)
    assert parser.get("Service", "NoNewPrivileges") == "yes"
    assert parser.get("Service", "CapabilityBoundingSet") == ""
    assert parser.get("Service", "ProtectSystem") == "strict"
    assert parser.get("Service", "ProtectHome") == "read-only"
    assert parser.get("Service", "PrivateTmp") == "yes"
    assert parser.get("Service", "ProtectKernelTunables") == "yes"
    assert parser.get("Service", "ProtectKernelModules") == "yes"
    assert parser.get("Service", "ProtectControlGroups") == "yes"
    assert parser.get("Service", "RestrictNamespaces") == "yes"
    assert parser.get("Service", "RestrictRealtime") == "yes"
    assert parser.get("Service", "RestrictSUIDSGID") == "yes"
    assert parser.get("Service", "MemoryDenyWriteExecute") == "no"

    # 6. Permisos de escritura acotados a rutas del usuario
    rw_paths = parser.get("Service", "ReadWritePaths")
    assert "%h/.local/share/ubuntu-voice-monitor" in rw_paths
    assert "%h/.config/ubuntu-voice-monitor" in rw_paths

    # 7. No debe contener directivas de ejecución como root
    assert not parser.has_option("Service", "User")
    assert "User=root" not in content
    assert "Group=root" not in content


def test_packaging_scripts_prevent_root_and_lack_privileged_helpers() -> None:
    """Verifica que los scripts de instalación prohíban root y no usen sudo/su."""
    install_sh = ROOT_DIR / "packaging" / "install.sh"
    uninstall_sh = ROOT_DIR / "packaging" / "uninstall.sh"

    assert install_sh.is_file()
    assert uninstall_sh.is_file()

    for script in (install_sh, uninstall_sh):
        text = script.read_text(encoding="utf-8")
        assert text.startswith("#!/usr/bin/env bash")

        # Comprobación explícita de no-root
        assert "EUID" in text or "id -u" in text
        assert "NO EJECUTAR COMO ROOT" in text

        # Verificar ausencia de helpers privilegiados (sudo, pkexec, setuid)
        forbidden = re.compile(r"\b(sudo|pkexec|doas|setuid)\b")
        matches = forbidden.findall(text)
        assert len(matches) == 0, f"Helper privilegiado encontrado en {script}: {matches}"


def test_pyproject_packaging_metadata() -> None:
    """Verifica que pyproject.toml cumpla con los estándares PEP 621 para empaquetado."""
    pyproject_file = ROOT_DIR / "pyproject.toml"
    assert pyproject_file.is_file()

    content = pyproject_file.read_text(encoding="utf-8")
    assert 'name = "ubuntu-voice-monitor"' in content
    assert 'requires-python = ">=3.10"' in content
    assert 'narrator = "app.cli:main"' in content


def test_documentation_covers_lifecycle_platforms_and_packaging() -> None:
    """Verifica que el README contenga la documentación requerida por el MR 17."""
    readme_file = ROOT_DIR / "README.md"
    assert readme_file.is_file()

    content = readme_file.read_text(encoding="utf-8")

    # Plataformas objetivo
    assert "Ubuntu 22.04" in content
    assert "Ubuntu 24.04" in content
    assert "Debian 12" in content

    # Métodos de empaquetado / instalación
    assert "pipx" in content
    assert "venv" in content

    # Ciclo de vida del servicio systemd
    assert "systemctl --user enable --now" in content
    assert "systemctl --user stop" in content
    assert "systemctl --user restart" in content
    assert "journalctl --user" in content

    # WSL y limitaciones
    assert "WSL" in content
    assert "/etc/wsl.conf" in content
    assert "WSLg" in content

    # Desinstalación y actualización
    assert "Desinstalación" in content or "desinstalación" in content
    assert "Actualización" in content or "actualización" in content
