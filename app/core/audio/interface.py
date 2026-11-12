"""Interfaces base para generacin y reproduccin de audio."""

from abc import ABC, abstractmethod
from typing import Protocol

from app.domain.audio import AudioData


class AudioGenerator(ABC):
    """Interfaz para motores que transforman texto en audio."""

    @abstractmethod
    def generate(self, text: str) -> AudioData | None:
        """Convierte el texto en audio. Retorna None si falla."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre del generador (ej. gemini, espeak)."""
        pass


class AudioPlayer(ABC):
    """Interfaz para reproductores de audio en el sistema."""

    @abstractmethod
    def play(self, audio: AudioData) -> None:
        """Reproduce el audio de forma bloqueante (debe usarse en thread)."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Interrumpe la reproduccin en curso."""
        pass


class PlaybackObserver(Protocol):
    """Recibe avisos cuando el monitor reproduce su propia narración."""

    def own_playback_started(self) -> None:
        """Se invoca justo antes de reproducir."""

    def own_playback_finished(self) -> None:
        """Se invoca al terminar la reproducción, incluso si falló."""
