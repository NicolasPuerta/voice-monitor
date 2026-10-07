"""Punto de entrada de Ubuntu Voice Monitor."""

from app import __version__

STARTUP_MESSAGE: str = (
    f"Ubuntu Voice Monitor v{__version__} se inició correctamente."
)


def get_startup_message() -> str:
    """Construye el mensaje de inicio de la aplicación.

    Returns:
        Mensaje indicando que la aplicación se inició correctamente.
    """
    return STARTUP_MESSAGE


def main() -> int:
    """Ejecuta la aplicación.

    Por ahora solo muestra el mensaje de inicio; el monitoreo, Gemini y
    el audio se implementarán en commits posteriores.

    Returns:
        Código de salida del proceso (0 indica éxito).
    """
    print(get_startup_message())
    return 0
