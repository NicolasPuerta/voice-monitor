"""Adaptador para Piper TTS."""

import subprocess
import hashlib
import logging

from app.domain.audio import AudioData, AudioFormat
from app.core.audio.interface import AudioGenerator

logger = logging.getLogger(__name__)


class PiperGenerator(AudioGenerator):
    """Generador TTS usando Piper (Neural TTS offline)."""

    def __init__(self, model_path: str = "es_ES-enrique-medium.onnx") -> None:
        self.model_path = model_path

    @property
    def name(self) -> str:
        return "piper"

    def generate(self, text: str) -> AudioData | None:
        try:
            # Piper lee texto desde stdin y saca wav crudo por stdout
            cmd = ["piper", "--model", self.model_path, "--output_stdout"]

            result = subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15.0,
            )

            if result.returncode != 0:
                logger.error(f"Error piper: {result.stderr.decode(errors='ignore')}")
                return None

            audio_bytes = result.stdout
            if not audio_bytes:
                return None

            hash_key = hashlib.sha256(text.encode("utf-8")).hexdigest()
            return AudioData(data=audio_bytes, format=AudioFormat.WAV, hash_key=hash_key)

        except FileNotFoundError:
            logger.error("Piper no est instalado en el PATH.")
            return None
        except subprocess.TimeoutExpired:
            logger.error("Piper agot el tiempo de espera.")
            return None
        except Exception as e:
            logger.error(f"Error inesperado en Piper: {e}")
            return None
