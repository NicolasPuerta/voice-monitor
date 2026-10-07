"""Sanitización de líneas de comandos y rutas antes de guardarlas.

La línea de comandos original puede contener contraseñas, tokens o rutas
personales. Este módulo produce una versión segura, acotada en tamaño, que es
la única que sale del collector.
"""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Final

REDACTED: Final[str] = "***"
"""Marcador que reemplaza los valores sensibles."""

DEFAULT_MAX_ARGS: Final[int] = 8
"""Cantidad máxima de argumentos conservados."""

DEFAULT_MAX_ARG_LENGTH: Final[int] = 80
"""Longitud máxima de cada argumento."""

DEFAULT_MAX_LENGTH: Final[int] = 256
"""Longitud máxima de la línea de comandos resultante."""

_ELLIPSIS: Final[str] = "…"

# Sensitive words must not be preceded by a letter, so "bypass" is not "pass"
_SENSITIVE = (
    r"(?<![a-z])(?:pass(?:word|wd|phrase)?|pwd|secret|token|api[-_]?key|auth"
    r"|credential|private[-_]?key|access[-_]?key)"
)
_KEY_VALUE = re.compile(
    rf"^(?P<key>-{{0,2}}[\w.-]*{_SENSITIVE}[\w.-]*)=(?P<value>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_SENSITIVE_FLAG = re.compile(
    rf"^-{{1,2}}[\w.-]*{_SENSITIVE}[\w.-]*$", re.IGNORECASE
)
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/\s@]+@", re.IGNORECASE)
_BEARER = re.compile(r"\b(?P<kind>bearer|basic)\s+\S+", re.IGNORECASE)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _truncate(text: str, limit: int) -> str:
    """Recorta un texto a un máximo de caracteres, marcando el corte.

    Args:
        text: Texto a recortar.
        limit: Longitud máxima, incluyendo el marcador de corte.

    Returns:
        El texto original o su versión recortada.
    """
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + _ELLIPSIS


def redact_home(text: str, home: str | None = None) -> str:
    """Reemplaza el directorio personal por ``~`` dentro de un texto.

    Args:
        text: Texto que puede contener rutas del directorio personal.
        home: Directorio personal. Por defecto, el del usuario actual.

    Returns:
        El texto con el directorio personal ocultado.
    """
    home_dir = str(Path.home()) if home is None else home
    if len(home_dir) <= 1:  # Empty or "/" would redact every path
        return text
    pattern = re.escape(home_dir.rstrip("/\\")) + r"(?=$|[/\\\s:=])"
    return re.sub(pattern, "~", text)


def _redact_sensitive_values(args: Sequence[str]) -> list[str]:
    """Oculta los valores de opciones sensibles (contraseñas, tokens, etc.).

    Args:
        args: Argumentos originales.

    Returns:
        Nueva lista con los valores sensibles reemplazados.
    """
    result: list[str] = []
    redact_next = False
    for arg in args:
        if redact_next:
            result.append(REDACTED)
            redact_next = False
            continue
        match = _KEY_VALUE.match(arg)
        if match:
            result.append(f"{match['key']}={REDACTED}")
            continue
        if _SENSITIVE_FLAG.match(arg):
            redact_next = True
        result.append(arg)
    return result


def _clean_argument(arg: str, *, redact_home_dir: bool, home: str | None) -> str:
    """Limpia un argumento individual.

    Args:
        arg: Argumento a limpiar.
        redact_home_dir: Si es verdadero, oculta el directorio personal.
        home: Directorio personal a ocultar. Por defecto, el del usuario actual.

    Returns:
        El argumento sin credenciales en URLs ni caracteres de control.
    """
    cleaned = _URL_CREDENTIALS.sub(rf"\g<scheme>{REDACTED}@", arg)
    cleaned = _BEARER.sub(rf"\g<kind> {REDACTED}", cleaned)
    cleaned = _CONTROL_CHARS.sub(" ", cleaned)
    if redact_home_dir:
        cleaned = redact_home(cleaned, home)
    return cleaned


def sanitize_cmdline(
    args: Sequence[str],
    *,
    redact_home_dir: bool = True,
    home: str | None = None,
    max_args: int = DEFAULT_MAX_ARGS,
    max_arg_length: int = DEFAULT_MAX_ARG_LENGTH,
    max_length: int = DEFAULT_MAX_LENGTH,
) -> str:
    """Genera una versión segura y acotada de una línea de comandos.

    Oculta valores de opciones sensibles (``--password x``, ``--token=x``,
    ``API_KEY=x``), credenciales en URLs, cabeceras ``Bearer``/``Basic`` y el
    directorio personal; elimina caracteres de control y limita la cantidad y
    longitud de los argumentos.

    Args:
        args: Argumentos originales del proceso.
        redact_home_dir: Si es verdadero, oculta el directorio personal.
        home: Directorio personal a ocultar. Por defecto, el del usuario actual.
        max_args: Cantidad máxima de argumentos conservados.
        max_arg_length: Longitud máxima de cada argumento.
        max_length: Longitud máxima del resultado.

    Returns:
        La línea de comandos sanitizada; cadena vacía si no hay argumentos.
    """
    redacted = _redact_sensitive_values(args)
    kept = [
        _truncate(
            _clean_argument(arg, redact_home_dir=redact_home_dir, home=home),
            max_arg_length,
        )
        for arg in redacted[:max_args]
    ]
    text = " ".join(kept)
    if len(redacted) > max_args:
        text = f"{text} {_ELLIPSIS}"
    return _truncate(text, max_length)
