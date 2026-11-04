"""Pruebas del generador de voz de Gemini (modelos TTS)."""

import io
import wave
from unittest.mock import MagicMock, patch

from app.core.audio.adapters.gemini import GeminiAudioGenerator, pcm_to_wav
from app.core.config import GeminiSettings, Settings
from app.domain.audio import AudioFormat


def _settings() -> Settings:
    return Settings(
        gemini=GeminiSettings(enabled=True, api_key="k", tts_voice="Puck")
    )


def _response(data: bytes, mime_type: str) -> MagicMock:
    part = MagicMock()
    part.inline_data.data = data
    part.inline_data.mime_type = mime_type
    response = MagicMock()
    response.candidates[0].content.parts = [part]
    return response


def test_pcm_to_wav_writes_valid_header() -> None:
    wav_bytes = pcm_to_wav(b"\x00\x00" * 2400, sample_rate=24_000)
    with wave.open(io.BytesIO(wav_bytes)) as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 24_000
        assert wav.getnframes() == 2400


@patch("app.core.audio.adapters.gemini.genai")
def test_gemini_audio_wraps_raw_pcm_as_wav(mock_genai: MagicMock) -> None:
    generator = GeminiAudioGenerator(_settings())
    generate = mock_genai.Client.return_value.models.generate_content
    generate.return_value = _response(b"\x01\x00" * 100, "audio/L16;codec=pcm;rate=16000")

    audio = generator.generate("Hola")

    assert audio is not None
    assert audio.format == AudioFormat.WAV
    with wave.open(io.BytesIO(audio.data)) as wav:
        assert wav.getframerate() == 16_000
    kwargs = generate.call_args.kwargs
    assert kwargs["model"] == "gemini-2.5-flash-preview-tts"
    assert kwargs["config"].response_modalities == ["AUDIO"]
    voice = kwargs["config"].speech_config.voice_config.prebuilt_voice_config
    assert voice.voice_name == "Puck"


@patch("app.core.audio.adapters.gemini.genai")
def test_gemini_audio_returns_none_on_error(mock_genai: MagicMock) -> None:
    generator = GeminiAudioGenerator(_settings())
    mock_genai.Client.return_value.models.generate_content.side_effect = RuntimeError
    assert generator.generate("Hola") is None


def test_gemini_audio_disabled_without_key() -> None:
    generator = GeminiAudioGenerator(Settings(gemini=GeminiSettings(enabled=False)))
    assert generator.client is None
    assert generator.generate("Hola") is None
