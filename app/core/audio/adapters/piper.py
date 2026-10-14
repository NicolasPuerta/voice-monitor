"""Adaptador para Piper TTS."""

import hashlib
import io
import logging
import subprocess
import wave
from typing import Any

from app.core.audio.interface import AudioGenerator
from app.domain.audio import AudioData, AudioFormat

logger = logging.getLogger(__name__)


class PiperGenerator(AudioGenerator):
    """Generador TTS usando Piper de forma residente en memoria.

    Mantiene el modelo neuronal cargado en memoria RAM para evitar el
    costo de inicialización y el pico de CPU en cada síntesis.
    """

    def __init__(self, model_path: str = "es_ES-enrique-medium.onnx") -> None:
        self.model_path = model_path
        self._voice: Any | None = None
        self._load_voice()

    @property
    def name(self) -> str:
        return "piper"

    def _load_voice(self) -> None:
        """Carga el modelo ONNX en RAM una sola vez al inicio."""
        try:
            from piper import PiperVoice  # type: ignore[import-not-found]

            logger.info(
                "Cargando modelo residente de Piper en RAM: %s", self.model_path
            )
            self._voice = PiperVoice.load(self.model_path)
            logger.info("Modelo residente de Piper cargado exitosamente.")
        except ImportError:
            logger.debug(
                "Librería 'piper-tts' no encontrada en Python. "
                "Se intentará modo subproceso CLI si es necesario."
            )
        except Exception as exc:
            logger.warning(
                "No se pudo cargar el modelo residente de Piper (%s): %s",
                self.model_path,
                exc,
            )

    def generate(self, text: str) -> AudioData | None:
        """Sintetiza texto a audio WAV sin recargar el modelo."""
        # 1. Modo Residente en Memoria (Nativo Python API)
        if self._voice is not None:
            try:
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as wav_file:
                    self._voice.synthesize_wav(text, wav_file)

                audio_bytes = buffer.getvalue()
                if audio_bytes:
                    hash_key = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    return AudioData(
                        data=audio_bytes,
                        format=AudioFormat.WAV,
                        hash_key=hash_key,
                    )
            except Exception as exc:
                logger.error("Error en síntesis con Piper residente: %s", exc)
                return None

        # 2. Modo CLI de respaldo (si piper-tts no está en el entorno Python)
        try:
            cmd = ["piper", "--model", self.model_path, "--output_stdout"]
            result = subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15.0,
            )
            if result.returncode != 0:
                logger.error(
                    "Error piper CLI: %s", result.stderr.decode(errors="ignore")
                )
                return None

            audio_bytes = result.stdout
            if not audio_bytes:
                return None

            hash_key = hashlib.sha256(text.encode("utf-8")).hexdigest()
            return AudioData(
                data=audio_bytes, format=AudioFormat.WAV, hash_key=hash_key
            )
        except FileNotFoundError:
            logger.debug("Piper no está instalado en el sistema.")
            return None
        except Exception as exc:
            logger.error("Error ejecutando Piper CLI: %s", exc)
            return None
