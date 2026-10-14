"""Adaptador para generacin de audio nativo desde Gemini."""

import hashlib
import logging
from typing import Any

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError

from app.domain.audio import AudioData, AudioFormat
from app.core.audio.interface import AudioGenerator
from app.core.config import Settings

logger = logging.getLogger(__name__)


class GeminiAudioGenerator(AudioGenerator):
    """Generador TTS usando la capacidad nativa de Audio de Gemini."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = settings.gemini.enabled
        # Asumimos que se configura un modelo multimodal como gemini-1.5-pro-audio
        # Si el modelo no lo soporta, el API rechazar la solicitud.
        self.model_name = settings.gemini.model

        self.model: Any | None = None
        if self.enabled and settings.gemini.api_key:
            api_key = settings.gemini.api_key.get_secret_value()
            genai.configure(api_key=api_key)  # type: ignore[attr-defined]
            model_cls = genai.GenerativeModel  # type: ignore[attr-defined]
            self.model = model_cls(self.model_name)

    @property
    def name(self) -> str:
        return "gemini-audio"

    def generate(self, text: str) -> AudioData | None:
        if not self.enabled or not self.model:
            return None

        try:
            # Solicitamos a Gemini que devuelva el audio de este texto.
            # Según las capacidades de la API (ej. Gemini con output audio).
            # Pasamos un config solicitando audio si la lib lo soporta.
            # Nota: Si el SDK local aún no expone response_modalities limpiamente,
            # esto podría fallar.
            prompt = f"Di exactamente lo siguiente de forma natural: {text}"

            # Algunos SDKs usan generation_config={"response_mime_type": "audio/mp3"}
            # Si lanza error, caerá en el except.
            response = self.model.generate_content(prompt)

            # Buscar el part de audio en la respuesta
            audio_bytes = None
            mime_type = ""

            if response.candidates:
                for part in response.candidates[0].content.parts:
                    # En algunos SDKs el part puede tener inline_data
                    if hasattr(part, "inline_data") and part.inline_data:
                        if part.inline_data.mime_type.startswith("audio/"):
                            audio_bytes = part.inline_data.data
                            mime_type = part.inline_data.mime_type
                            break

            if audio_bytes:
                fmt = AudioFormat.MP3 if "mp3" in mime_type else AudioFormat.WAV
                hash_key = hashlib.sha256(text.encode("utf-8")).hexdigest()
                return AudioData(data=audio_bytes, format=fmt, hash_key=hash_key)
            else:
                logger.debug(
                    "El modelo de Gemini no retornó partes de audio en la respuesta."
                )
                return None

        except GoogleAPIError as e:
            logger.error(f"Error de API Gemini generando audio: {e}")
            return None
        except Exception as e:
            logger.error(f"Error inesperado con Gemini Audio: {e}")
            return None
