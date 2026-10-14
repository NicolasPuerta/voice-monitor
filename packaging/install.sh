#!/usr/bin/env bash
# ==============================================================================
# Script de instalación para Ubuntu 22.04 / 24.04 y Debian 12 (MR 17)
# Instala Ubuntu Voice Monitor y configura el servicio systemd de usuario.
# NO EJECUTAR COMO ROOT.
# ==============================================================================
set -euo pipefail

# 1. Verificación de seguridad: no ejecutar como root
if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    echo "ERROR: Este instalador configura un servicio de usuario no privilegiado." >&2
    echo "Por favor, ejecútelo como su usuario normal sin privilegios." >&2
    exit 1
fi

echo "=================================================================="
echo "    Instalador de Ubuntu Voice Monitor (systemd User Service)     "
echo "=================================================================="

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ubuntu-voice-monitor"
USER_SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_NAME="voice-monitor.service"

mkdir -p "$USER_CONFIG_DIR"
mkdir -p "$USER_SYSTEMD_DIR"
mkdir -p "${XDG_DATA_HOME:-$HOME/.local/share}/ubuntu-voice-monitor"

# 2. Localizar o instalar el comando narrator
NARRATOR_BIN=""
if command -v narrator >/dev/null 2>&1; then
    NARRATOR_BIN="$(command -v narrator)"
    echo "[✓] Binario 'narrator' encontrado en: $NARRATOR_BIN"
elif [ -f "$HOME/.local/bin/narrator" ]; then
    NARRATOR_BIN="$HOME/.local/bin/narrator"
    echo "[✓] Binario 'narrator' encontrado en: $NARRATOR_BIN"
else
    echo "[!] 'narrator' no encontrado en PATH. Intentando instalación..."
    if command -v pipx >/dev/null 2>&1; then
        echo "[*] Instalando mediante pipx..."
        pipx install "$PROJECT_DIR"
        NARRATOR_BIN="$(command -v narrator || echo "$HOME/.local/bin/narrator")"
    else
        echo "[!] pipx no está instalado. En Ubuntu 24.04/Debian 12 se recomienda:"
        echo "    apt install pipx && pipx ensurepath"
        echo "    O instale en un entorno virtual (venv) y ejecute este script."
        exit 1
    fi
fi

# 3. Configuración externa (.env / config.env)
if [ ! -f "$USER_CONFIG_DIR/config.env" ]; then
    if [ -f "$PROJECT_DIR/.env.example" ]; then
        cp "$PROJECT_DIR/.env.example" "$USER_CONFIG_DIR/config.env"
        echo "[✓] Archivo de configuración creado en: $USER_CONFIG_DIR/config.env"
    else
        touch "$USER_CONFIG_DIR/config.env"
    fi
else
    echo "[✓] Configuración existente detectada en: $USER_CONFIG_DIR/config.env"
fi

# 4. Instalar y ajustar el archivo de servicio systemd
SERVICE_SRC="$PROJECT_DIR/packaging/systemd/$SERVICE_NAME"
SERVICE_DEST="$USER_SYSTEMD_DIR/$SERVICE_NAME"

if [ -f "$SERVICE_SRC" ]; then
    sed "s|ExecStart=.*|ExecStart=$NARRATOR_BIN start --foreground|g" "$SERVICE_SRC" > "$SERVICE_DEST"
    echo "[✓] Servicio de usuario instalado en: $SERVICE_DEST"
else
    echo "ERROR: No se encontró el archivo de servicio en $SERVICE_SRC" >&2
    exit 1
fi

# 5. Recargar systemd de usuario si está disponible
if command -v systemctl >/dev/null 2>&1; then
    if systemctl --user daemon-reload >/dev/null 2>&1; then
        echo "[✓] systemd daemon-reload ejecutado con éxito."
    else
        echo "[!] Aviso: No se pudo conectar a systemctl --user."
        echo "    Si está en WSL, verifique que /etc/wsl.conf contenga '[boot]\nsystemd=true'."
    fi
fi

echo "=================================================================="
echo "    Instalación completada con éxito.                             "
echo "=================================================================="
echo "Para habilitar e iniciar el servicio ahora:"
echo "    systemctl --user enable --now $SERVICE_NAME"
echo ""
echo "Para consultar el estado:"
echo "    systemctl --user status $SERVICE_NAME"
echo "    narrator status"
echo ""
echo "Para consultar los registros en vivo:"
echo "    journalctl --user -u voice-monitor -f"
echo "=================================================================="
