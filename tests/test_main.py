"""Pruebas básicas del punto de entrada."""

import pytest

from app.main import get_startup_message, main


def test_get_startup_message_mentions_app_name() -> None:
    """Verifica que el mensaje de inicio incluya el nombre de la aplicación."""
    message = get_startup_message()
    assert "Ubuntu Voice Monitor" in message
    assert "se inició correctamente" in message


def test_main_prints_startup_message(capsys: pytest.CaptureFixture[str]) -> None:
    """Verifica que main imprima el mensaje de inicio y retorne 0."""
    exit_code = main()
    captured = capsys.readouterr()
    assert exit_code == 0
    assert get_startup_message() in captured.out
