"""Pruebas de la configuración centralizada."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import AppEnv, NarrationVerbosity, Settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_default_settings() -> None:
    """Verifica los valores por defecto de todos los grupos."""
    settings = Settings.load()
    assert settings.app.app_env is AppEnv.DEVELOPMENT
    assert settings.app.log_level == "INFO"
    assert settings.collector.interval_s == 5.0
    assert settings.collector.battery_interval_s == 15.0
    assert settings.collector.adaptive is True
    assert settings.gemini.enabled is False
    assert settings.gemini.model == "gemini-2.5-flash"
    assert settings.gemini.api_key is None
    assert settings.narration.verbosity is NarrationVerbosity.NORMAL
    assert settings.narration.min_gap_s == 10.0
    assert settings.narration.max_burst == 3
    assert settings.narration.event_ttl_s == 60.0
    assert settings.storage.db_path.name == "events.db"
    assert "~" not in str(settings.storage.db_path)
    assert settings.privacy.redact_home is True
    assert settings.dnd.enabled is False
    assert settings == Settings()


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que las variables de entorno sobrescriban los valores."""
    values = {
        "APP_ENV": "Production",
        "LOG_LEVEL": "debug",
        "COLLECTOR_INTERVAL_S": "2.5",
        "COLLECTOR_BATTERY_INTERVAL_S": "30",
        "COLLECTOR_ADAPTIVE": "false",
        "GEMINI_ENABLED": "true",
        "GEMINI_MODEL": "gemini-test",
        "GEMINI_API_KEY": "test-key",
        "NARRATION_VERBOSITY": "VERBOSE",
        "NARRATION_MIN_GAP_S": "5",
        "NARRATION_MAX_BURST": "7",
        "NARRATION_EVENT_TTL_S": "120",
        "STORAGE_DB_PATH": "/tmp/test.db",
        "PRIVACY_REDACT_HOME": "false",
        "DND_ENABLED": "true",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    settings = Settings.load()
    assert settings.app.app_env is AppEnv.PRODUCTION
    assert settings.app.log_level == "DEBUG"
    assert settings.collector.interval_s == 2.5
    assert settings.collector.battery_interval_s == 30
    assert settings.collector.adaptive is False
    assert settings.gemini.enabled is True
    assert settings.gemini.model == "gemini-test"
    assert settings.narration.verbosity is NarrationVerbosity.VERBOSE
    assert settings.narration.min_gap_s == 5
    assert settings.narration.max_burst == 7
    assert settings.narration.event_ttl_s == 120
    assert settings.storage.db_path == Path("/tmp/test.db")
    assert settings.privacy.redact_home is False
    assert settings.dnd.enabled is True


def test_settings_from_env_file(tmp_path: Path) -> None:
    """Verifica la carga desde un archivo .env y la prioridad del entorno."""
    env_file = tmp_path / ".env"
    env_file.write_text("LOG_LEVEL=warning\nNARRATION_MAX_BURST=9\n", encoding="utf-8")
    settings = Settings.load(env_file)
    assert settings.app.log_level == "WARNING"
    assert settings.narration.max_burst == 9


def test_environment_has_priority_over_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifica que el entorno tenga prioridad sobre el archivo .env."""
    env_file = tmp_path / ".env"
    env_file.write_text("LOG_LEVEL=warning\n", encoding="utf-8")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    assert Settings.load(env_file).app.log_level == "ERROR"


def test_env_example_is_valid_and_matches_defaults() -> None:
    """Verifica que .env.example sea válido y coincida con los valores por defecto."""
    from_example = Settings.load(PROJECT_ROOT / ".env.example")
    assert from_example == Settings.load()


def test_empty_values_use_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que las variables vacías usen el valor por defecto."""
    monkeypatch.setenv("LOG_LEVEL", "")
    monkeypatch.setenv("COLLECTOR_INTERVAL_S", "")
    settings = Settings.load()
    assert settings.app.log_level == "INFO"
    assert settings.collector.interval_s == 5.0


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("APP_ENV", "staging"),
        ("LOG_LEVEL", "VERBOSE"),
        ("COLLECTOR_INTERVAL_S", "0"),
        ("COLLECTOR_INTERVAL_S", "abc"),
        ("COLLECTOR_BATTERY_INTERVAL_S", "100000"),
        ("COLLECTOR_ADAPTIVE", "maybe"),
        ("NARRATION_VERBOSITY", "loud"),
        ("NARRATION_MIN_GAP_S", "-1"),
        ("NARRATION_MAX_BURST", "0"),
        ("NARRATION_EVENT_TTL_S", "0"),
    ],
)
def test_invalid_values_raise_error(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    """Verifica que los valores inválidos lancen un error de validación."""
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings.load()


def test_battery_interval_cannot_be_lower_than_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifica que el intervalo en batería no sea menor que el normal."""
    monkeypatch.setenv("COLLECTOR_INTERVAL_S", "10")
    monkeypatch.setenv("COLLECTOR_BATTERY_INTERVAL_S", "5")
    with pytest.raises(ValidationError, match="COLLECTOR_BATTERY_INTERVAL_S"):
        Settings.load()


def test_event_ttl_cannot_be_lower_than_min_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifica que el TTL no sea menor que el espacio mínimo entre narraciones."""
    monkeypatch.setenv("NARRATION_MIN_GAP_S", "30")
    monkeypatch.setenv("NARRATION_EVENT_TTL_S", "10")
    with pytest.raises(ValidationError, match="NARRATION_EVENT_TTL_S"):
        Settings.load()


def test_gemini_requires_api_key_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que habilitar Gemini sin API key sea un error."""
    monkeypatch.setenv("GEMINI_ENABLED", "true")
    with pytest.raises(ValidationError, match="GEMINI_API_KEY"):
        Settings.load()


def test_gemini_api_key_is_read_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifica la lectura de GEMINI_API_KEY desde el entorno."""
    monkeypatch.setenv("GEMINI_API_KEY", "env-key-456")
    api_key = Settings.load().gemini.api_key
    assert api_key is not None
    assert api_key.get_secret_value() == "env-key-456"


def test_gemini_api_key_is_not_exposed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que la API key no aparezca en repr, str ni serialización."""
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret")
    settings = Settings.load()
    assert "super-secret" not in repr(settings)
    assert "super-secret" not in str(settings)
    assert "super-secret" not in settings.model_dump_json()


def test_settings_are_immutable() -> None:
    """Verifica que la configuración no pueda modificarse."""
    settings = Settings.load()
    with pytest.raises(ValidationError):
        settings.dnd = settings.dnd  # type: ignore[misc]
    with pytest.raises(ValidationError):
        settings.dnd.enabled = True  # type: ignore[misc]


def test_source_code_contains_no_hardcoded_api_key() -> None:
    """Verifica que el código fuente no contenga claves con formato de Google."""
    for source_file in (PROJECT_ROOT / "app").rglob("*.py"):
        assert "AIza" not in source_file.read_text(encoding="utf-8"), source_file
