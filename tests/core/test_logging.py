"""Pruebas del logging centralizado."""

import io
import logging
import re
from collections.abc import Iterator

import pytest

from app.core.logging import (
    ROOT_LOGGER_NAME,
    configure_logging,
    get_logger,
    normalize_log_level,
)


@pytest.fixture(autouse=True)
def _restore_app_logger() -> Iterator[None]:
    """Restaura el estado del logger de la aplicación tras cada prueba."""
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    handlers, level, propagate = list(logger.handlers), logger.level, logger.propagate
    yield
    logger.handlers = handlers
    logger.setLevel(level)
    logger.propagate = propagate


def test_log_line_includes_timestamp_and_level() -> None:
    """Verifica que cada línea incluya timestamp, nivel y mensaje."""
    stream = io.StringIO()
    configure_logging("INFO", stream)
    get_logger("tests").info("hola")
    pattern = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| INFO     \| app\.tests \| hola$"
    assert re.match(pattern, stream.getvalue().strip())


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_all_levels_are_supported(level: str) -> None:
    """Verifica que cada nivel soportado se emita con su nombre."""
    stream = io.StringIO()
    configure_logging("DEBUG", stream)
    get_logger("tests").log(getattr(logging, level), "mensaje")
    assert f"| {level}" in stream.getvalue()


def test_messages_below_configured_level_are_filtered() -> None:
    """Verifica que se filtren los mensajes de nivel inferior al configurado."""
    stream = io.StringIO()
    configure_logging("WARNING", stream)
    logger = get_logger("tests")
    logger.info("oculto")
    logger.warning("visible")
    output = stream.getvalue()
    assert "oculto" not in output
    assert "visible" in output


def test_level_is_case_insensitive() -> None:
    """Verifica que el nivel no distinga mayúsculas de minúsculas."""
    assert normalize_log_level(" error ") == "ERROR"
    assert configure_logging("error", io.StringIO()).level == logging.ERROR


def test_invalid_level_raises_error() -> None:
    """Verifica que un nivel no soportado lance ValueError."""
    with pytest.raises(ValueError, match="Nivel de log no soportado"):
        configure_logging("VERBOSE", io.StringIO())


def test_configure_logging_is_idempotent() -> None:
    """Verifica que reconfigurar no duplique los mensajes."""
    first, second = io.StringIO(), io.StringIO()
    configure_logging("INFO", first)
    configure_logging("INFO", second)
    get_logger("tests").info("una vez")
    assert first.getvalue() == ""
    assert second.getvalue().count("una vez") == 1


def test_get_logger_prefixes_name() -> None:
    """Verifica que los loggers cuelguen del logger raíz de la aplicación."""
    assert get_logger("monitor").name == "app.monitor"
    assert get_logger("app.core.config").name == "app.core.config"
    assert get_logger("app").name == "app"
