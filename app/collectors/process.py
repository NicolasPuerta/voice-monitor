"""Collector de procesos basado en psutil (solo lectura)."""

import time
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

import psutil
from pydantic import ValidationError

from app.collectors.base import Collector
from app.collectors.procfs import DEFAULT_PROC_ROOT, read_proc_cgroup, read_proc_cmdline
from app.collectors.sanitize import redact_home, sanitize_cmdline
from app.core.logging import get_logger
from app.domain.snapshots import ProcessSnapshot

logger = get_logger(__name__)

ReadT = TypeVar("ReadT")


class MemoryInfoLike(Protocol):
    """Subconjunto de la información de memoria de un proceso."""

    @property
    def rss(self) -> int:
        """Memoria residente, en bytes."""


class ProcessHandle(Protocol):
    """Subconjunto de ``psutil.Process`` que usa el collector.

    Permite inyectar procesos falsos en las pruebas.
    """

    @property
    def pid(self) -> int:
        """Identificador del proceso."""

    def oneshot(self) -> AbstractContextManager[None]:
        """Agrupa las lecturas para reducir el costo de acceso a ``/proc``."""

    def ppid(self) -> int:
        """Identificador del proceso padre."""

    def name(self) -> str:
        """Nombre del proceso."""

    def status(self) -> str:
        """Estado del proceso."""

    def cpu_percent(self, interval: float | None = None) -> float:
        """Uso de CPU desde la llamada anterior."""

    def num_threads(self) -> int:
        """Cantidad de hilos."""

    def memory_info(self) -> MemoryInfoLike:
        """Información de memoria."""

    def exe(self) -> str:
        """Ruta del ejecutable."""

    def cmdline(self) -> list[str]:
        """Argumentos del proceso."""

    def username(self) -> str:
        """Usuario propietario."""


ProcessIterFactory = Callable[[], Iterable[ProcessHandle]]
"""Función que devuelve los procesos actuales."""


@dataclass(frozen=True)
class CollectionStats:
    """Resumen de la última recolección."""

    seen: int = 0
    """Procesos listados por el sistema."""

    collected: int = 0
    """Procesos convertidos en snapshot."""

    vanished: int = 0
    """Procesos que desaparecieron durante la lectura."""

    failed: int = 0
    """Procesos descartados por un error inesperado de lectura o validación."""

    duration_s: float = 0.0
    """Duración de la recolección, en segundos."""


def _read(getter: Callable[[], ReadT]) -> ReadT | None:
    """Ejecuta una lectura tolerando la falta de datos o de permisos.

    Un proceso zombi sigue existiendo, por lo que no se considera desaparecido.
    ``psutil.NoSuchProcess`` sí se propaga para descartar el proceso completo.

    Args:
        getter: Función sin argumentos que realiza la lectura.

    Returns:
        El valor leído, o ``None`` si no está disponible.
    """
    try:
        return getter()
    except (psutil.AccessDenied, psutil.ZombieProcess, PermissionError, FileNotFoundError):
        return None


class ProcessCollector(Collector[tuple[ProcessSnapshot, ...]]):
    """Obtiene información básica de los procesos sin modificarlos.

    Usa solo lecturas de psutil y de ``/proc``; nunca ejecuta comandos ni envía
    señales. Un proceso que desaparece o niega el acceso durante la lectura no
    interrumpe la recolección.

    El primer ``collect`` devuelve ``cpu_percent`` igual a 0 (psutil necesita dos
    lecturas para calcular el uso); desde el segundo, el valor es real.
    """

    def __init__(
        self,
        *,
        include_username: bool = False,
        include_cmdline: bool = True,
        include_cgroup: bool = False,
        redact_home_dir: bool = True,
        process_iter: ProcessIterFactory | None = None,
        proc_root: Path = DEFAULT_PROC_ROOT,
    ) -> None:
        """Crea el collector.

        Args:
            include_username: Si es verdadero, consulta el usuario de cada proceso
                (es costoso y es un dato personal, por eso está desactivado).
            include_cmdline: Si es verdadero, incluye la línea de comandos
                sanitizada.
            include_cgroup: Si es verdadero, lee ``/proc/<pid>/cgroup``.
            redact_home_dir: Si es verdadero, oculta el directorio personal.
            process_iter: Fuente de procesos; por defecto ``psutil.process_iter``.
            proc_root: Raíz de procfs (configurable para pruebas).
        """
        self._include_username = include_username
        self._include_cmdline = include_cmdline
        self._include_cgroup = include_cgroup
        self._redact_home_dir = redact_home_dir
        self._process_iter: ProcessIterFactory = process_iter or psutil.process_iter
        self._proc_root = proc_root
        self._last_stats = CollectionStats()

    @property
    def name(self) -> str:
        """Nombre del collector.

        Returns:
            El nombre ``process``.
        """
        return "process"

    @property
    def last_stats(self) -> CollectionStats:
        """Resumen de la última recolección.

        Returns:
            Estadísticas de la última llamada a ``collect``.
        """
        return self._last_stats

    def collect(self) -> tuple[ProcessSnapshot, ...]:
        """Lee todos los procesos visibles.

        Returns:
            Un snapshot por cada proceso leído correctamente.
        """
        started = time.perf_counter()
        snapshots: list[ProcessSnapshot] = []
        seen = vanished = failed = 0
        for process in self._process_iter():
            seen += 1
            try:
                snapshots.append(self._build_snapshot(process))
            except (psutil.NoSuchProcess, ProcessLookupError):
                vanished += 1
            except (psutil.Error, OSError, ValidationError) as error:
                failed += 1
                logger.debug("Proceso descartado por un error de lectura: %s", error)
        stats = CollectionStats(
            seen=seen,
            collected=len(snapshots),
            vanished=vanished,
            failed=failed,
            duration_s=time.perf_counter() - started,
        )
        self._last_stats = stats
        logger.debug(
            "Procesos recolectados: %d de %d (desaparecidos=%d, con error=%d) en %.1f ms.",
            stats.collected,
            stats.seen,
            stats.vanished,
            stats.failed,
            stats.duration_s * 1000,
        )
        return tuple(snapshots)

    def _build_snapshot(self, process: ProcessHandle) -> ProcessSnapshot:
        """Construye el snapshot de un proceso.

        Args:
            process: Proceso a leer.

        Returns:
            El snapshot con los datos disponibles.

        Raises:
            psutil.NoSuchProcess: Si el proceso desapareció durante la lectura.
        """
        with process.oneshot():
            pid = process.pid
            memory = _read(process.memory_info)
            return ProcessSnapshot(
                pid=pid,
                name=_read(process.name) or "unknown",
                parent_pid=_read(process.ppid),
                username=_read(process.username) if self._include_username else None,
                status=_read(process.status),
                cpu_percent=max(_read(process.cpu_percent) or 0.0, 0.0),
                memory_rss_bytes=memory.rss if memory is not None else None,
                num_threads=_read(process.num_threads),
                executable=self._read_executable(process),
                cmdline=self._read_cmdline(process),
                cgroup=(
                    read_proc_cgroup(pid, self._proc_root)
                    if self._include_cgroup
                    else None
                ),
            )

    def _read_executable(self, process: ProcessHandle) -> str | None:
        """Lee la ruta del ejecutable, ocultando el directorio personal.

        Args:
            process: Proceso a leer.

        Returns:
            La ruta del ejecutable, o ``None`` si no está disponible.
        """
        executable = _read(process.exe)
        if not executable:
            return None
        return redact_home(executable) if self._redact_home_dir else executable

    def _read_cmdline(self, process: ProcessHandle) -> str | None:
        """Lee y sanitiza la línea de comandos; la original no se conserva.

        Si psutil no puede leerla, se intenta directamente ``/proc/<pid>/cmdline``.

        Args:
            process: Proceso a leer.

        Returns:
            La línea de comandos sanitizada, o ``None`` si no está disponible.
        """
        if not self._include_cmdline:
            return None
        args = _read(process.cmdline)
        if args is None:
            args = read_proc_cmdline(process.pid, self._proc_root)
        if not args:
            return None
        return sanitize_cmdline(args, redact_home_dir=self._redact_home_dir)
