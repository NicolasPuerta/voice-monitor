"""Punto de entrada de Ubuntu Voice Monitor."""

import sys

from app import __version__

STARTUP_MESSAGE: str = f"Ubuntu Voice Monitor v{__version__} se inició correctamente."


def get_startup_message() -> str:
    """Construye el mensaje de inicio de la aplicación.

    Returns:
        Mensaje indicando que la aplicación se inició correctamente.
    """
    return STARTUP_MESSAGE


def main(argv: list[str] | None = None, run_loop: bool | None = None) -> int:
    """Ejecuta la aplicación Ubuntu Voice Monitor.

    ``python -m app [opciones]`` equivale a ``narrator start --foreground
    [opciones]``: el monitor se arma en un único lugar (``app.cli``).

    Args:
        argv: Argumentos de línea de comandos opcionales (p. ej. ``--demo``,
            ``--iterations N``, ``--test-gemini``, ``--no-audio``).
        run_loop: Si debe ejecutar el bucle de monitoreo continuo.
            Por defecto es True, salvo cuando se ejecuta bajo pruebas (pytest).

    Returns:
        Código de salida del proceso (0 indica éxito).
    """
    print(get_startup_message())

    if run_loop is None:
        run_loop = "pytest" not in sys.modules

    if not run_loop:
        return 0

    from app.cli import main as cli_main

    args = list(sys.argv[1:] if argv is None else argv)
    return cli_main(["start", "--foreground", *args])
