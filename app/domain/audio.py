"""Modelos de dominio para el subsistema de audio."""

from enum import Enum

from app.domain.base import DomainModel


class AudioFormat(str, Enum):
    WAV = "wav"
    MP3 = "mp3"
    OGG = "ogg"


class AudioData(DomainModel):
    """Encapsula un buffer de audio generado."""
    
    data: bytes
    """Bytes crudos del archivo de audio."""
    
    format: AudioFormat
    """Formato del audio."""
    
    hash_key: str
    """Hash del texto original para cacheo."""
