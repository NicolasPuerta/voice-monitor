#!/usr/bin/env bash
# ==============================================================================
# Script de desinstalación limpia para Ubuntu / Debian (MR 17)
# NO EJECUTAR COMO ROOT.
# ==============================================================================
set -euo pipefail

if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    echo "ERROR: Este desinstalador gestiona un servicio de usuario no privilegiado." >&2
    echo "Por favor, ejecútelo como su usuario normal sin privilegios." >&2
    exit 1
fi

echo "=================================================================="
echo "    Desinstalador de Ubuntu Voice Monitor                         "
echo "=================================================================="

SERVICE_NAME="voice-monitor.service"
USER_SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_DEST="$USER_SYSTEMD_DIR/$SERVICE_NAME"

# 1. Detener y deshabilitar el servicio si está activo
if command -v systemctl >/dev/null 2>&1; then
    echo "[*] Deteniendo y deshabilitando $SERVICE_NAME..."
    systemctl --user stop "$SERVICE_NAME" >/dev/null 2>&1 || true
    systemctl --user disable "$SERVICE_NAME" >/dev/null 2>&1 || true
fi

# 2. Eliminar el archivo unit
if [ -f "$SERVICE_DEST" ]; then
    rm -f "$SERVICE_DEST"
    echo "[✓] Archivo de servicio eliminado: $SERVICE_DEST"
fi

# 3. Recargar daemon de systemd
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    echo "[✓] systemd daemon-reload ejecutado."
fi

# 4. Desinstalar paquete pipx si existe
if command -v pipx >/dev/null 2>&1; then
    if pipx list | grep -q "ubuntu-voice-monitor"; then
        echo "[*] Desinstalando paquete de pipx..."
        pipx uninstall ubuntu-voice-monitor || true
        echo "[✓] Paquete pipx desinstalado."
    fi
fi

echo "=================================================================="
echo "    Desinstalación del servicio completada.                      "
echo "=================================================================="
echo "Nota: Los archivos de configuración y base de datos se conservan en:"
echo "  - Configuración: ${XDG_CONFIG_HOME:-$HOME/.config}/ubuntu-voice-monitor"
echo "  - Base de datos: ${XDG_DATA_HOME:-$HOME/.local/share}/ubuntu-voice-monitor"
echo "Para eliminarlos manualmente:"
echo "  rm -rf \"${XDG_CONFIG_HOME:-$HOME/.config}/ubuntu-voice-monitor\""
echo "  rm -rf \"${XDG_DATA_HOME:-$HOME/.local/share}/ubuntu-voice-monitor\""
echo "=================================================================="
