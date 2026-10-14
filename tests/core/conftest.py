"""Fixtures compartidas de las pruebas de configuración."""

import os

import pytest

ENV_PREFIXES = (
    "APP_",
    "LOG_LEVEL",
    "COLLECTOR_",
    "GEMINI_",
    "NARRATION_",
    "STORAGE_",
    "PRIVACY_",
    "DND_",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Elimina las variables de la aplicación para aislar cada prueba."""
    for name in list(os.environ):
        if name.upper().startswith(ENV_PREFIXES):
            monkeypatch.delenv(name)
