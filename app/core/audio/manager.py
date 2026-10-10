"""Gestor de colas de audio y cache."""

import threading
import queue
import hashlib
import logging

from app.domain.audio import AudioData
from app.core.audio.interface import AudioGenerator, AudioPlayer

logger = logging.getLogger(__name__)


class AudioQueueManager:
    """Maneja la cola de generacin y reproduccin en hilos separados."""

    def __init__(
        self,
        player: AudioPlayer,
        primary_generator: AudioGenerator,
        fallback_generators: list[AudioGenerator] | None = None,
    ) -> None:
        self.player = player
        self.primary_generator = primary_generator
        self.fallback_generators = fallback_generators or []

        self.cache: dict[str, AudioData] = {}

        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def enqueue(self, text: str) -> None:
        """Enva texto a la cola para ser narrado."""
        if not text.strip():
            return
        self._queue.put(text)

    def cancel_all(self) -> None:
        """Limpia la cola pendiente y detiene cualquier audio en reproduccin."""
        # Vaciar la cola
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        # Detener la reproduccin fsica actual
        self.player.stop()

    def shutdown(self) -> None:
        """Detiene el hilo limpiamente."""
        self.cancel_all()
        self._stop_event.set()
        self._queue.put(None)
        self._worker_thread.join(timeout=2.0)

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                text = self._queue.get(timeout=1.0)
                if text is None:
                    break

                self._process_text(text)
                self._queue.task_done()
            except queue.Empty:
                continue

    def _process_text(self, text: str) -> None:
        # 1. Comprobar cache (muy til para alertas repetidas)
        hash_key = hashlib.sha256(text.encode("utf-8")).hexdigest()

        audio = self.cache.get(hash_key)

        # 2. Si no hay cache, generarlo probando por orden de prioridad
        if not audio:
            audio = self._generate_with_fallback(text)
            if audio:
                # Cache limitado a memoria temporal para no devorar RAM
                if len(self.cache) > 100:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[hash_key] = audio

        # 3. Reproducir (bloquea el worker hasta terminar el audio)
        if audio and not self._stop_event.is_set():
            self.player.play(audio)

    def _generate_with_fallback(self, text: str) -> AudioData | None:
        engines = [self.primary_generator] + self.fallback_generators
        for engine in engines:
            logger.debug(f"Intentando generar audio con {engine.name}...")
            audio = engine.generate(text)
            if audio:
                return audio

        logger.warning("No se pudo generar audio con ningn motor.")
        return None
