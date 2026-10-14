"""Pruebas de la sanitización de líneas de comandos."""

import pytest

from app.collectors.sanitize import REDACTED, redact_home, sanitize_cmdline

HOME = "/home/alice"


def test_empty_cmdline_returns_empty_string() -> None:
    """Verifica que una lista vacía produzca una cadena vacía."""
    assert sanitize_cmdline([]) == ""


def test_plain_cmdline_is_preserved() -> None:
    """Verifica que una línea sin datos sensibles no cambie."""
    assert sanitize_cmdline(["/usr/bin/python3", "-m", "http.server"]) == (
        "/usr/bin/python3 -m http.server"
    )


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["mysql", "--password", "s3cret"], f"mysql --password {REDACTED}"),
        (["mysql", "--password=s3cret"], f"mysql --password={REDACTED}"),
        (["app", "--api-key=abc123"], f"app --api-key={REDACTED}"),
        (["app", "--API_TOKEN", "abc"], f"app --API_TOKEN {REDACTED}"),
        (["env", "DB_PASSWORD=hunter2", "run"], f"env DB_PASSWORD={REDACTED} run"),
        (["env", "GEMINI_API_KEY=xyz"], f"env GEMINI_API_KEY={REDACTED}"),
        (["curl", "--private-key", "k"], f"curl --private-key {REDACTED}"),
    ],
)
def test_sensitive_values_are_redacted(args: list[str], expected: str) -> None:
    """Verifica que se oculten los valores de opciones sensibles."""
    result = sanitize_cmdline(args)
    assert result == expected
    for leaked in ("s3cret", "abc123", "hunter2", "xyz"):
        assert leaked not in result


def test_non_sensitive_options_with_similar_names_are_kept() -> None:
    """Verifica que 'bypass' no se confunda con 'pass'."""
    assert sanitize_cmdline(["tool", "--bypass-cache", "yes"]) == (
        "tool --bypass-cache yes"
    )


def test_option_value_with_sensitive_path_is_kept() -> None:
    """Verifica que solo la clave determine si un valor es sensible."""
    assert sanitize_cmdline(["app", "--config=/etc/token.json"]) == (
        "app --config=/etc/token.json"
    )


def test_url_credentials_are_redacted() -> None:
    """Verifica que se oculten las credenciales dentro de URLs."""
    result = sanitize_cmdline(["curl", "https://bob:pw123@example.com/path"])
    assert result == f"curl https://{REDACTED}@example.com/path"


def test_bearer_header_is_redacted() -> None:
    """Verifica que se oculte el valor de una cabecera Bearer."""
    result = sanitize_cmdline(["curl", "-H", "Authorization: Bearer abc.def"])
    assert "abc.def" not in result
    assert f"Bearer {REDACTED}" in result


def test_home_directory_is_redacted() -> None:
    """Verifica que el directorio personal se reemplace por ~."""
    result = sanitize_cmdline(["vim", f"{HOME}/notes.txt"], home=HOME)
    assert result == "vim ~/notes.txt"


def test_home_redaction_can_be_disabled() -> None:
    """Verifica que se pueda conservar el directorio personal."""
    result = sanitize_cmdline(["vim", f"{HOME}/n"], home=HOME, redact_home_dir=False)
    assert result == f"vim {HOME}/n"


def test_redact_home_does_not_touch_similar_prefixes() -> None:
    """Verifica que /home/alice2 no se confunda con /home/alice."""
    assert redact_home("/home/alice2/x", HOME) == "/home/alice2/x"
    assert redact_home("/home/alice", HOME) == "~"
    assert redact_home("KEY=/home/alice/x", HOME) == "KEY=~/x"


@pytest.mark.parametrize("home", ["", "/"])
def test_redact_home_ignores_degenerate_home(home: str) -> None:
    """Verifica que un home vacío o '/' no oculte todas las rutas."""
    assert redact_home("/usr/bin/tool", home) == "/usr/bin/tool"


def test_control_characters_are_removed() -> None:
    """Verifica que se eliminen saltos de línea y otros caracteres de control."""
    assert sanitize_cmdline(["echo", "a\nb\x1bc"]) == "echo a b c"


def test_long_arguments_are_truncated() -> None:
    """Verifica que cada argumento se recorte a la longitud máxima."""
    result = sanitize_cmdline(["x" * 500], max_arg_length=20)
    assert len(result) == 20
    assert result.endswith("…")


def test_argument_count_is_limited() -> None:
    """Verifica que se limite la cantidad de argumentos conservados."""
    result = sanitize_cmdline(["a", "b", "c", "d"], max_args=2)
    assert result == "a b …"


def test_total_length_is_limited() -> None:
    """Verifica que el resultado no supere la longitud máxima."""
    args = ["y" * 60] * 8
    assert len(sanitize_cmdline(args, max_length=100)) == 100


def test_sensitive_value_beyond_max_args_is_never_leaked() -> None:
    """Verifica que los valores sensibles se oculten antes de recortar."""
    result = sanitize_cmdline(["a", "--password", "topsecret"], max_args=3)
    assert "topsecret" not in result


def test_input_is_not_mutated() -> None:
    """Verifica que la lista original no se modifique."""
    args = ["mysql", "--password", "s3cret"]
    sanitize_cmdline(args)
    assert args == ["mysql", "--password", "s3cret"]
