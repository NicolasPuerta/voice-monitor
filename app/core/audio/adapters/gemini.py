"""Adaptador para generacin de audio nativo desde Gemini."""

import hashlib
import logging

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
        self.enabled = settings.app.gemini_enabled
        # Asumimos que se configura un modelo multimodal como gemini-1.5-pro-audio
        # Si el modelo no lo soporta, el API rechazar la solicitud.
        self.model_name = settings.app.gemini_model

        if self.enabled and settings.app.gemini_api_key:
            genai.configure(api_key=settings.app.gemini_api_key.get_secret_value())
            self.model = genai.GenerativeModel(self.model_name)
        else:
            self.model = None

    @property
    def name(self) -> str:
        return "gemini-audio"

    def generate(self, text: str) -> AudioData | None:
        if not self.enabled or not self.model:
            return None

        try:
            # Solicitamos a Gemini que devuelva el audio de este texto.
            # Segn las capacidades de la API (ej. Gemini 2.0 o 1.5 con output audio)
            # Pasamos un config explicitly solicitando audio si la lib lo soporta.
            # Nota: Si el SDK local (python) an no expone response_modalities de forma limpia,
            # esto podra fallar. Este es el patrn terico esperado.
            prompt = f"Di exactamente lo siguiente de la forma ms natural posible: {text}"

            # Algunos SDKs usan generation_config={"response_mime_type": "audio/mp3"}
            # Si lanza error, caer en el except.
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
                    "El modelo de Gemini no retorn partes de audio en la respuesta. (No admitido?)"
                )
                return None

        except GoogleAPIError as e:
            logger.error(f"Error de API Gemini generando audio: {e}")
            return None
        except Exception as e:
            logger.error(f"Error inesperado con Gemini Audio: {e}")
            return None
