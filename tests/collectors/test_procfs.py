"""Pruebas de la lectura de archivos de procfs."""

from pathlib import Path

import pytest

from app.collectors.procfs import (
    MAX_PROC_FILE_BYTES,
    parse_cgroup,
    read_proc_cgroup,
    read_proc_cmdline,
)


def write_proc_file(root: Path, pid: int, name: str, content: bytes) -> None:
    """Crea un archivo falso en ``<root>/<pid>/<name>``."""
    directory = root / str(pid)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(content)


def test_read_proc_cmdline_splits_on_nul(tmp_path: Path) -> None:
    """Verifica que los argumentos se separen por bytes nulos."""
    write_proc_file(tmp_path, 10, "cmdline", b"python\0-m\0app\0")
    assert read_proc_cmdline(10, tmp_path) == ["python", "-m", "app"]


def test_read_proc_cmdline_handles_invalid_utf8(tmp_path: Path) -> None:
    """Verifica que bytes inválidos no rompan la lectura."""
    write_proc_file(tmp_path, 10, "cmdline", b"tool\0\xff\xfe\0")
    assert read_proc_cmdline(10, tmp_path)[0] == "tool"


def test_read_proc_cmdline_missing_process_returns_empty(tmp_path: Path) -> None:
    """Verifica que un proceso inexistente (FileNotFoundError) devuelva vacío."""
    assert read_proc_cmdline(999, tmp_path) == []


def test_read_proc_cmdline_empty_file_returns_empty(tmp_path: Path) -> None:
    """Verifica que un hilo de kernel (cmdline vacío) devuelva vacío."""
    write_proc_file(tmp_path, 2, "cmdline", b"")
    assert read_proc_cmdline(2, tmp_path) == []


def test_read_proc_cmdline_permission_error_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifica que PermissionError devuelva vacío en lugar de propagarse."""
    write_proc_file(tmp_path, 10, "cmdline", b"secret\0")

    def deny(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("denegado")

    monkeypatch.setattr(Path, "open", deny)
    assert read_proc_cmdline(10, tmp_path) == []


def test_read_proc_cmdline_is_size_limited(tmp_path: Path) -> None:
    """Verifica que se limite la cantidad de bytes leídos."""
    write_proc_file(tmp_path, 10, "cmdline", b"a" * (MAX_PROC_FILE_BYTES * 4))
    assert len(read_proc_cmdline(10, tmp_path)[0]) == MAX_PROC_FILE_BYTES


def test_parse_cgroup_prefers_v2_unified_hierarchy() -> None:
    """Verifica que se prefiera la jerarquía unificada de cgroup v2."""
    content = "12:cpu:/legacy\n0::/user.slice/user-1000.slice/session-3.scope\n"
    assert parse_cgroup(content) == "/user.slice/user-1000.slice/session-3.scope"


def test_parse_cgroup_falls_back_to_first_v1_path() -> None:
    """Verifica el uso de la primera ruta cuando solo hay cgroup v1."""
    assert parse_cgroup("12:cpu,cpuacct:/docker/abc\n11:memory:/docker/abc\n") == (
        "/docker/abc"
    )


@pytest.mark.parametrize("content", ["", "\n", "garbage", "0::\n"])
def test_parse_cgroup_without_valid_lines_returns_none(content: str) -> None:
    """Verifica que un contenido inválido devuelva None."""
    assert parse_cgroup(content) is None


def test_read_proc_cgroup(tmp_path: Path) -> None:
    """Verifica la lectura completa del cgroup de un proceso."""
    write_proc_file(tmp_path, 10, "cgroup", b"0::/system.slice/ssh.service\n")
    assert read_proc_cgroup(10, tmp_path) == "/system.slice/ssh.service"


def test_read_proc_cgroup_missing_returns_none(tmp_path: Path) -> None:
    """Verifica que un cgroup inexistente (FileNotFoundError) devuelva None."""
    assert read_proc_cgroup(999, tmp_path) is None
