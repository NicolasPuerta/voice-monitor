"""Pruebas del subsistema de audio y colas de reproduccin."""

import hashlib
from unittest.mock import MagicMock, patch

from app.domain.audio import AudioData, AudioFormat
from app.core.audio.manager import AudioQueueManager
from app.core.audio.interface import AudioGenerator, AudioPlayer


class DummyPlayer(AudioPlayer):
    def __init__(self) -> None:
        self.played: list[AudioData] = []
        self.stopped = False

    def play(self, audio: AudioData) -> None:
        self.played.append(audio)

    def stop(self) -> None:
        self.stopped = True


class DummyGenerator(AudioGenerator):
    def __init__(self, name: str, should_fail: bool = False) -> None:
        self._name = name
        self.should_fail = should_fail
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def generate(self, text: str) -> AudioData | None:
        self.calls += 1
        if self.should_fail:
            return None
        return AudioData(
            data=b"dummy_audio_bytes",
            format=AudioFormat.WAV,
            hash_key=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )


def test_audio_queue_manager_caching_and_playback() -> None:
    player = DummyPlayer()
    gen = DummyGenerator("dummy")

    manager = AudioQueueManager(player, primary_generator=gen)

    # 1. Enviar texto, debe generar y reproducir
    manager._process_text("Prueba uno")

    assert gen.calls == 1
    assert len(player.played) == 1

    # 2. Enviar el MISMO texto, debe usar cache y reproducir sin llamar al generador
    manager._process_text("Prueba uno")

    assert gen.calls == 1
    assert len(player.played) == 2

    manager.shutdown()


def test_audio_queue_manager_fallback() -> None:
    player = DummyPlayer()
    primary = DummyGenerator("failing_primary", should_fail=True)
    fallback = DummyGenerator("working_fallback", should_fail=False)

    manager = AudioQueueManager(
        player, primary_generator=primary, fallback_generators=[fallback]
    )

    manager._process_text("Prueba dos")

    assert primary.calls == 1
    assert fallback.calls == 1
    assert len(player.played) == 1

    manager.shutdown()


def test_audio_queue_manager_cancellation() -> None:
    player = DummyPlayer()
    gen = DummyGenerator("dummy")
    manager = AudioQueueManager(player, primary_generator=gen)

    # Encolar multiples sin bloquear el hilo de test (en el _queue real)
    manager.enqueue("1")
    manager.enqueue("2")
    manager.enqueue("3")

    assert not manager._queue.empty()

    # Cancelar todo
    manager.cancel_all()

    # La cola debera estar vaca y se detuvo la reproduccin fsica
    assert manager._queue.empty()
    assert player.stopped

    manager.shutdown()


@patch("app.core.audio.player.subprocess.Popen")
@patch("app.core.audio.player.os.remove")
def test_system_audio_player_execution(
    mock_remove: MagicMock, mock_popen: MagicMock
) -> None:
    from app.core.audio.player import SystemAudioPlayer

    player = SystemAudioPlayer()
    # Mockear is_tool_installed
    with patch.object(player, "_is_tool_installed", return_value=True):
        audio = AudioData(data=b"wavdata", format=AudioFormat.WAV, hash_key="abc")
        player.play(audio)

        assert mock_popen.called
        assert mock_remove.called
