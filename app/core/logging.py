"""Logging centralizado de la aplicación."""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Final, TextIO

SUPPORTED_LOG_LEVELS: Final[tuple[str, ...]] = (
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
)
"""Niveles de logging soportados por la aplicación."""

ROOT_LOGGER_NAME: Final[str] = "app"
"""Nombre del logger raíz de la aplicación; todos los demás cuelgan de él."""

LOG_FORMAT: Final[str] = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
"""Formato de los logs: timestamp, nivel, logger y mensaje."""

DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
"""Formato del timestamp de los logs."""

_HANDLER_NAME: Final[str] = "app-console"

LOG_FILE_MAX_BYTES: Final[int] = 5 * 1024 * 1024
"""Tamaño máximo del archivo de log antes de rotarlo."""

LOG_FILE_BACKUPS: Final[int] = 3
"""Copias rotadas que se conservan (narrator.log.1 ... .3)."""


def normalize_log_level(level: str) -> str:
    """Normaliza un nivel de logging y valida que esté soportado.

    Args:
        level: Nivel de logging (sin distinguir mayúsculas de minúsculas).

    Returns:
        El nivel de logging en mayúsculas.

    Raises:
        ValueError: Si el nivel no está soportado.
    """
    normalized = level.strip().upper()
    if normalized not in SUPPORTED_LOG_LEVELS:
        supported = ", ".join(SUPPORTED_LOG_LEVELS)
        raise ValueError(
            f"Nivel de log no soportado: '{level}'. Valores válidos: {supported}"
        )
    return normalized


def configure_logging(
    level: str = "INFO",
    stream: TextIO | None = None,
    log_file: Path | None = None,
) -> logging.Logger:
    """Configura el logger raíz de la aplicación.

    Es idempotente: llamarla de nuevo reemplaza el handler anterior en lugar
    de duplicar los mensajes.

    Args:
        level: Nivel de logging (DEBUG, INFO, WARNING, ERROR o CRITICAL).
        stream: Destino de los logs. Por defecto ``sys.stderr``.
        log_file: Si se indica, los logs van a este archivo con rotación
            (en lugar de ``stream``); se usa al correr en segundo plano.

    Returns:
        El logger raíz de la aplicación ya configurado.

    Raises:
        ValueError: Si el nivel no está soportado.
    """
    normalized = normalize_log_level(level)

    logger = logging.getLogger(ROOT_LOGGER_NAME)
    for existing in [h for h in logger.handlers if h.get_name() == _HANDLER_NAME]:
        logger.removeHandler(existing)
        existing.close()

    handler: logging.Handler
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=LOG_FILE_MAX_BYTES,
            backupCount=LOG_FILE_BACKUPS,
            encoding="utf-8",
        )
    else:
        handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(normalized)
    # Avoid duplicated output if the root logger is configured elsewhere
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """Obtiene un logger hijo del logger raíz de la aplicación.

    Args:
        name: Nombre del logger, normalmente ``__name__``.

    Returns:
        Un logger cuyo nombre empieza por ``app``.
    """
    if name == ROOT_LOGGER_NAME or name.startswith(f"{ROOT_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")
