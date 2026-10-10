"""Módulo de gestión y reproducción de audio."""

from app.core.audio.interface import AudioGenerator, AudioPlayer
from app.core.audio.manager import AudioQueueManager
from app.core.audio.player import SystemAudioPlayer
from app.core.audio.adapters.espeak import EspeakGenerator
from app.core.audio.adapters.piper import PiperGenerator
from app.core.audio.adapters.gemini import GeminiAudioGenerator

__all__ = [
    "AudioGenerator",
    "AudioPlayer",
    "AudioQueueManager",
    "EspeakGenerator",
    "GeminiAudioGenerator",
    "PiperGenerator",
    "SystemAudioPlayer",
]
