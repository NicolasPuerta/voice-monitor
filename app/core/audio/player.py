"""Reproductor de audio mediante comandos del sistema operativo (aplay / ffplay)."""

import os
import subprocess
import tempfile
import logging

from app.domain.audio import AudioData, AudioFormat
from app.core.audio.interface import AudioPlayer

logger = logging.getLogger(__name__)


class SystemAudioPlayer(AudioPlayer):
    """Reproduce audio usando binarios nativos del SO (Linux/WSL)."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None

    def play(self, audio: AudioData) -> None:
        """Escribe el buffer a un archivo temporal y lo reproduce bloqueando."""
        ext = f".{audio.format.value}"

        # Crear un archivo temporal para que el reproductor del sistema lo lea
        fd, path = tempfile.mkstemp(suffix=ext)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(audio.data)

            cmd = self._get_play_command(path, audio.format)
            if not cmd:
                logger.error(
                    "No se encontr un comando de reproduccin vlido en este sistema."
                )
                return

            self._process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._process.wait()  # Espera bloqueante hasta que termine el audio

        except Exception as e:
            logger.error(f"Error al reproducir audio: {e}")
        finally:
            self._process = None
            try:
                os.remove(path)
            except OSError:
                pass

    def stop(self) -> None:
        """Interrumpe la reproduccin inmediatamente."""
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    def _get_play_command(self, filepath: str, fmt: AudioFormat) -> list[str] | None:
        """Determina el comando ms adecuado basado en las herramientas disponibles y el entorno WSL/Ubuntu."""

        # Si es wav, aplay es lo ms nativo en linux
        if fmt == AudioFormat.WAV:
            if self._is_tool_installed("aplay"):
                return ["aplay", "-q", filepath]
            if self._is_tool_installed("paplay"):
                return ["paplay", filepath]

        # Fallback genrico y para mp3/ogg usando ffplay
        if self._is_tool_installed("ffplay"):
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", filepath]

        return None

    def _is_tool_installed(self, tool: str) -> bool:
        try:
            subprocess.run(
                ["which", tool],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False
        except FileNotFoundError:
            return False
