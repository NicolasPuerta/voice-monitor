"""Gestor de estado en ejecución y control entre procesos (IPC ligero)."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any

import psutil

logger = logging.getLogger(__name__)

DEFAULT_RUNTIME_DIR = Path.home() / ".local" / "share" / "ubuntu-voice-monitor"


class RuntimeManager:
    """Administra archivos de PID, estado en vivo y señales de control para el CLI."""

    def __init__(self, runtime_dir: Path | str | None = None) -> None:
        self.runtime_dir = Path(runtime_dir) if runtime_dir else DEFAULT_RUNTIME_DIR
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

        self.pid_file = self.runtime_dir / "narrator.pid"
        self.state_file = self.runtime_dir / "runtime_state.json"
        self.control_file = self.runtime_dir / "control.json"

    def get_running_pid(self) -> int | None:
        """Retorna el PID del proceso si está activo, o None si no lo está."""
        if not self.pid_file.exists():
            return None

        try:
            content = self.pid_file.read_text(encoding="utf-8").strip()
            if not content:
                self.remove_pid()
                return None
            pid = int(content)
            if psutil.pid_exists(pid):
                proc = psutil.Process(pid)
                if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                    return pid
            # PID huérfano o proceso ya terminado
            self.remove_pid()
            return None
        except (ValueError, OSError, psutil.NoSuchProcess, psutil.AccessDenied):
            self.remove_pid()
            return None

    def write_pid(self, pid: int) -> None:
        """Registra el PID del proceso en el archivo de control."""
        try:
            self.pid_file.write_text(str(pid), encoding="utf-8")
        except OSError as exc:
            logger.warning("No se pudo escribir el archivo PID: %s", exc)

    def remove_pid(self) -> None:
        """Elimina el archivo de PID si existe."""
        try:
            if self.pid_file.exists():
                self.pid_file.unlink()
        except OSError as exc:
            logger.debug("Error eliminando archivo PID: %s", exc)

    def write_state(self, state: dict[str, Any]) -> None:
        """Escribe atómicamente el estado en vivo del monitor."""
        tmp_file = self.state_file.with_suffix(".tmp")
        try:
            data = dict(state)
            data["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
            tmp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_file.replace(self.state_file)
        except OSError as exc:
            logger.debug("Error escribiendo estado en vivo: %s", exc)
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except OSError:
                    pass

    def read_state(self) -> dict[str, Any] | None:
        """Lee el estado en vivo registrado del monitor."""
        if not self.state_file.exists():
            return None
        try:
            content = self.state_file.read_text(encoding="utf-8")
            return json.loads(content)  # type: ignore[no-any-return]
        except (OSError, json.JSONDecodeError):
            return None

    def send_command(self, command: str, **kwargs: Any) -> None:
        """Envía un comando de control (ej. pause, resume, stop) al proceso activo."""
        payload = {
            "command": command,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        }
        tmp_file = self.control_file.with_suffix(".tmp")
        try:
            tmp_file.write_text(json.dumps(payload), encoding="utf-8")
            tmp_file.replace(self.control_file)
        except OSError as exc:
            logger.warning("Error enviando comando '%s': %s", command, exc)

    def consume_command(self) -> dict[str, Any] | None:
        """Lee y consume el comando de control pendiente si existe."""
        if not self.control_file.exists():
            return None
        try:
            content = self.control_file.read_text(encoding="utf-8")
            self.control_file.unlink(missing_ok=True)
            return json.loads(content)  # type: ignore[no-any-return]
        except (OSError, json.JSONDecodeError):
            if self.control_file.exists():
                try:
                    self.control_file.unlink()
                except OSError:
                    pass
            return None

    def stop_daemon(self, timeout_s: float = 3.0) -> bool:
        """Detiene el demonio en ejecución enviándole la orden de detención."""
        pid = self.get_running_pid()
        if pid is None:
            return False

        self.send_command("stop")

        # Esperar que termine pacíficamente
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if not psutil.pid_exists(pid):
                self.remove_pid()
                return True
            time.sleep(0.1)

        # Si aún vive, forzar terminación
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=1.5)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            try:
                proc.kill()
            except Exception:
                pass

        self.remove_pid()
        return True
