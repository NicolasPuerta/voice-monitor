"""Adaptador para generación de audio nativo desde Gemini (modelos TTS)."""

import hashlib
import io
import logging
import re
import wave
from typing import Any

from google import genai
from google.genai import types

from app.domain.audio import AudioData, AudioFormat
from app.core.audio.interface import AudioGenerator
from app.core.config import Settings

logger = logging.getLogger(__name__)

# Los modelos TTS de Gemini devuelven PCM lineal de 16 bits, mono, 24 kHz
DEFAULT_SAMPLE_RATE = 24_000


def pcm_to_wav(pcm: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE) -> bytes:
    """Envuelve PCM de 16 bits mono en un contenedor WAV reproducible."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def _sample_rate(mime_type: str) -> int:
    """Extrae ``rate=`` de un MIME como ``audio/L16;codec=pcm;rate=24000``."""
    match = re.search(r"rate=(\d+)", mime_type)
    return int(match.group(1)) if match else DEFAULT_SAMPLE_RATE


class GeminiAudioGenerator(AudioGenerator):
    """Generador TTS usando los modelos de voz nativos de Gemini."""

    def __init__(self, settings: Settings, timeout_s: float = 30.0) -> None:
        self.settings = settings
        self.enabled = settings.gemini.enabled
        self.model_name = settings.gemini.tts_model
        self.voice = settings.gemini.tts_voice

        self.client: Any | None = None
        if self.enabled and settings.gemini.api_key:
            self.client = genai.Client(
                api_key=settings.gemini.api_key.get_secret_value(),
                http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
            )

    @property
    def name(self) -> str:
        return "gemini-audio"

    def generate(self, text: str) -> AudioData | None:
        if not self.enabled or not self.client:
            return None

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=f"Lee en español, con tono natural y tranquilo: {text}",
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=self.voice
                            )
                        )
                    ),
                ),
            )

            inline = None
            if response.candidates and response.candidates[0].content:
                for part in response.candidates[0].content.parts or []:
                    if part.inline_data and part.inline_data.data:
                        inline = part.inline_data
                        break

            if inline is None or inline.data is None:
                logger.debug("Gemini no retornó partes de audio en la respuesta.")
                return None

            mime_type = inline.mime_type or ""
            data = inline.data
            if "mp3" in mime_type or "mpeg" in mime_type:
                fmt = AudioFormat.MP3
            elif "wav" in mime_type:
                fmt = AudioFormat.WAV
            else:
                # audio/L16 (PCM crudo): hace falta la cabecera WAV
                data = pcm_to_wav(data, _sample_rate(mime_type))
                fmt = AudioFormat.WAV

            hash_key = hashlib.sha256(text.encode("utf-8")).hexdigest()
            return AudioData(data=data, format=fmt, hash_key=hash_key)

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Error con Gemini Audio: %s", e)
            return None
