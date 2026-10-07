"""Lectura segura y de solo lectura de archivos de ``/proc/<pid>``."""

from pathlib import Path
from typing import Final

DEFAULT_PROC_ROOT: Final[Path] = Path("/proc")
"""Directorio raíz de procfs."""

MAX_PROC_FILE_BYTES: Final[int] = 8192
"""Máximo de bytes leídos de un archivo de ``/proc`` para acotar memoria."""

MAX_CGROUP_LENGTH: Final[int] = 256
"""Longitud máxima de la ruta de cgroup devuelta."""


def _read_limited(path: Path) -> bytes | None:
    """Lee como máximo ``MAX_PROC_FILE_BYTES`` bytes de un archivo.

    Args:
        path: Archivo a leer.

    Returns:
        Los bytes leídos, o ``None`` si el archivo no existe, no hay permisos o
        el proceso desapareció durante la lectura.
    """
    try:
        with path.open("rb") as handle:
            return handle.read(MAX_PROC_FILE_BYTES)
    except OSError:
        # Covers FileNotFoundError, PermissionError and ProcessLookupError
        return None


def read_proc_cmdline(pid: int, proc_root: Path = DEFAULT_PROC_ROOT) -> list[str]:
    """Lee los argumentos de ``/proc/<pid>/cmdline``.

    Args:
        pid: Identificador del proceso.
        proc_root: Raíz de procfs (configurable para pruebas).

    Returns:
        Lista de argumentos; vacía si no se pudo leer o el proceso no tiene.
    """
    raw = _read_limited(proc_root / str(pid) / "cmdline")
    if not raw:
        return []
    text = raw.decode("utf-8", errors="replace")
    return [arg for arg in text.split("\0") if arg]


def parse_cgroup(content: str) -> str | None:
    """Extrae la ruta de cgroup del contenido de ``/proc/<pid>/cgroup``.

    Prefiere la jerarquía unificada de cgroup v2 (``0::/ruta``); si no existe,
    usa la ruta de la primera línea válida.

    Args:
        content: Contenido del archivo ``cgroup``.

    Returns:
        La ruta de cgroup, o ``None`` si no hay ninguna.
    """
    fallback: str | None = None
    for line in content.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3 or not parts[2]:
            continue
        hierarchy, controllers, path = parts
        if hierarchy == "0" and not controllers:
            return path[:MAX_CGROUP_LENGTH]
        if fallback is None:
            fallback = path[:MAX_CGROUP_LENGTH]
    return fallback


def read_proc_cgroup(pid: int, proc_root: Path = DEFAULT_PROC_ROOT) -> str | None:
    """Lee la ruta de cgroup de ``/proc/<pid>/cgroup``.

    Args:
        pid: Identificador del proceso.
        proc_root: Raíz de procfs (configurable para pruebas).

    Returns:
        La ruta de cgroup, o ``None`` si no se pudo leer.
    """
    raw = _read_limited(proc_root / str(pid) / "cgroup")
    if raw is None:
        return None
    return parse_cgroup(raw.decode("utf-8", errors="replace"))
