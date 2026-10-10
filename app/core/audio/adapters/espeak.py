"""Adaptador para espeak-ng."""

import subprocess
import hashlib
import logging

from app.domain.audio import AudioData, AudioFormat
from app.core.audio.interface import AudioGenerator

logger = logging.getLogger(__name__)


class EspeakGenerator(AudioGenerator):
    """Generador TTS usando el comando espeak-ng (offline y rpido)."""

    def __init__(self, voice: str = "es-la") -> None:
        self.voice = voice

    @property
    def name(self) -> str:
        return "espeak-ng"

    def generate(self, text: str) -> AudioData | None:
        try:
            # -v voz, --stdout saca el wav crudo
            cmd = ["espeak-ng", "-v", self.voice, "--stdout", text]

            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10.0
            )

            if result.returncode != 0:
                logger.error(f"Error espeak: {result.stderr.decode(errors='ignore')}")
                return None

            audio_bytes = result.stdout
            if not audio_bytes:
                return None

            hash_key = hashlib.sha256(text.encode("utf-8")).hexdigest()
            return AudioData(data=audio_bytes, format=AudioFormat.WAV, hash_key=hash_key)

        except FileNotFoundError:
            logger.error("espeak-ng no est instalado en el sistema.")
            return None
        except subprocess.TimeoutExpired:
            logger.error("espeak-ng agot el tiempo de espera.")
            return None
        except Exception as e:
            logger.error(f"Error inesperado en espeak-ng: {e}")
            return None
