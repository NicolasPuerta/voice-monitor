"""Pruebas del ProcessCollector."""

import os
import random
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import psutil
import pytest

from app.collectors import Collector, ProcessCollector
from app.collectors.process import ProcessHandle

APP_DIR = Path(__file__).resolve().parents[2] / "app"
SECRET = "hunter2"


class FakeMemory:
    """Información de memoria falsa."""

    def __init__(self, rss: int) -> None:
        """Guarda la memoria residente."""
        self.rss = rss


class FakeProcess:
    """Proceso falso; cada atributo puede ser un valor o una excepción."""

    def __init__(self, pid: int, **attrs: object) -> None:
        """Crea el proceso con valores personalizados sobre los de por defecto."""
        self.pid = pid
        self.calls: list[str] = []
        self._attrs: dict[str, object] = {
            "ppid": 1,
            "name": f"proc{pid}",
            "status": "sleeping",
            "cpu_percent": 1.5,
            "num_threads": 4,
            "memory_info": FakeMemory(2048),
            "exe": f"/usr/bin/proc{pid}",
            "cmdline": [f"/usr/bin/proc{pid}", "--flag"],
            "username": "alice",
        }
        self._attrs.update(attrs)

    def _get(self, key: str) -> object:
        """Devuelve el valor configurado o lanza la excepción configurada."""
        self.calls.append(key)
        value = self._attrs[key]
        if isinstance(value, BaseException):
            raise value
        return value

    @contextmanager
    def oneshot(self) -> Iterator[None]:
        """Simula el contexto de lecturas agrupadas."""
        yield

    def ppid(self) -> int:
        """Proceso padre."""
        value = self._get("ppid")
        return int(str(value))

    def name(self) -> str:
        """Nombre."""
        return str(self._get("name"))

    def status(self) -> str:
        """Estado."""
        return str(self._get("status"))

    def cpu_percent(self, interval: float | None = None) -> float:
        """Uso de CPU."""
        del interval
        return float(self._get("cpu_percent"))  # type: ignore[arg-type]

    def num_threads(self) -> int:
        """Hilos."""
        value = self._get("num_threads")
        return int(str(value))

    def memory_info(self) -> FakeMemory:
        """Memoria."""
        value = self._get("memory_info")
        assert isinstance(value, FakeMemory)
        return value

    def exe(self) -> str:
        """Ejecutable."""
        return str(self._get("exe"))

    def cmdline(self) -> list[str]:
        """Argumentos."""
        value = self._get("cmdline")
        assert isinstance(value, list)
        return [str(item) for item in value]

    def username(self) -> str:
        """Usuario."""
        return str(self._get("username"))


def make_collector(*processes: FakeProcess, **options: object) -> ProcessCollector:
    """Crea un collector que lee los procesos falsos indicados."""

    def factory() -> list[ProcessHandle]:
        return list(processes)

    return ProcessCollector(process_iter=factory, **options)  # type: ignore[arg-type]


def test_collector_implements_interface() -> None:
    """Verifica que ProcessCollector cumpla el contrato Collector."""
    collector = ProcessCollector()
    assert isinstance(collector, Collector)
    assert collector.name == "process"


def test_collector_interface_cannot_be_instantiated() -> None:
    """Verifica que la interfaz Collector sea abstracta."""
    with pytest.raises(TypeError):
        Collector()  # type: ignore[abstract]


def test_collect_returns_domain_models() -> None:
    """Verifica que se devuelvan snapshots del dominio con los datos leídos."""
    snapshots = make_collector(FakeProcess(10), FakeProcess(11)).collect()
    assert [type(item).__name__ for item in snapshots] == ["ProcessSnapshot"] * 2
    first = snapshots[0]
    assert first.pid == 10
    assert first.parent_pid == 1
    assert first.name == "proc10"
    assert first.status == "sleeping"
    assert first.cpu_percent == 1.5
    assert first.num_threads == 4
    assert first.memory_rss_bytes == 2048
    assert first.executable == "/usr/bin/proc10"
    assert first.cmdline == "/usr/bin/proc10 --flag"
    assert first.username is None
    assert first.cgroup is None


def test_username_is_only_read_when_requested() -> None:
    """Verifica que el usuario no se consulte salvo que se pida."""
    process = FakeProcess(10)
    assert make_collector(process).collect()[0].username is None
    assert "username" not in process.calls
    with_user = make_collector(FakeProcess(10), include_username=True).collect()
    assert with_user[0].username == "alice"


def test_vanished_process_is_skipped_without_breaking_the_cycle() -> None:
    """Verifica que un proceso desaparecido no afecte a los demás."""
    collector = make_collector(
        FakeProcess(1),
        FakeProcess(2, memory_info=psutil.NoSuchProcess(2)),
        FakeProcess(3, name=ProcessLookupError()),
        FakeProcess(4),
    )
    snapshots = collector.collect()
    assert [item.pid for item in snapshots] == [1, 4]
    stats = collector.last_stats
    assert (stats.seen, stats.collected, stats.vanished, stats.failed) == (4, 2, 2, 0)


@pytest.mark.parametrize(
    "error",
    [
        psutil.AccessDenied(5),
        PermissionError("denegado"),
        FileNotFoundError("no existe"),
        psutil.ZombieProcess(5),
    ],
)
def test_unreadable_attributes_become_none(error: BaseException) -> None:
    """Verifica que los errores de lectura dejen el dato en None, no en excepción."""
    process = FakeProcess(
        5,
        ppid=error,
        status=error,
        num_threads=error,
        memory_info=error,
        exe=error,
        cmdline=error,
    )
    snapshot = make_collector(process).collect()[0]
    assert snapshot.pid == 5
    assert snapshot.parent_pid is None
    assert snapshot.status is None
    assert snapshot.num_threads is None
    assert snapshot.memory_rss_bytes is None
    assert snapshot.executable is None
    assert snapshot.cmdline is None


def test_zombie_process_is_kept_with_available_data() -> None:
    """Verifica que un zombi se conserve con los datos que sí se pueden leer."""
    zombie = psutil.ZombieProcess(7)
    process = FakeProcess(
        7, status="zombie", exe=zombie, cmdline=zombie, memory_info=zombie
    )
    collector = make_collector(process)
    snapshot = collector.collect()[0]
    assert snapshot.status == "zombie"
    assert snapshot.executable is None
    assert collector.last_stats.vanished == 0


def test_unknown_name_falls_back_to_placeholder() -> None:
    """Verifica que un nombre ilegible use un valor por defecto."""
    snapshot = make_collector(FakeProcess(9, name=psutil.AccessDenied(9))).collect()[0]
    assert snapshot.name == "unknown"


def test_negative_cpu_is_clamped() -> None:
    """Verifica que una CPU negativa se corrija a cero."""
    assert make_collector(FakeProcess(9, cpu_percent=-3.0)).collect()[0].cpu_percent == 0


def test_invalid_data_discards_only_that_process() -> None:
    """Verifica que datos inválidos descarten solo el proceso afectado."""
    collector = make_collector(FakeProcess(1, ppid=-5), FakeProcess(2))
    assert [item.pid for item in collector.collect()] == [2]
    assert collector.last_stats.failed == 1


def test_unexpected_psutil_error_discards_only_that_process() -> None:
    """Verifica que otros errores de psutil no rompan el ciclo."""
    collector = make_collector(
        FakeProcess(1, name=psutil.TimeoutExpired(1)), FakeProcess(2)
    )
    assert [item.pid for item in collector.collect()] == [2]
    assert collector.last_stats.failed == 1


def test_cmdline_is_sanitized_and_raw_value_never_stored() -> None:
    """Verifica que la cmdline salga sanitizada y sin el secreto original."""
    process = FakeProcess(3, cmdline=["mysql", "--password", SECRET, "--db=x"])
    snapshot = make_collector(process).collect()[0]
    assert snapshot.cmdline == "mysql --password *** --db=x"
    assert SECRET not in snapshot.model_dump_json()


def test_cmdline_can_be_disabled() -> None:
    """Verifica que no se lea la cmdline cuando está desactivada."""
    process = FakeProcess(3)
    snapshot = make_collector(process, include_cmdline=False).collect()[0]
    assert snapshot.cmdline is None
    assert "cmdline" not in process.calls


def test_cmdline_falls_back_to_proc_when_psutil_cannot_read_it(tmp_path: Path) -> None:
    """Verifica el respaldo a /proc/<pid>/cmdline cuando psutil niega el acceso."""
    (tmp_path / "3").mkdir()
    (tmp_path / "3" / "cmdline").write_bytes(f"tool\0--token={SECRET}\0".encode())
    process = FakeProcess(3, cmdline=psutil.AccessDenied(3))
    snapshot = make_collector(process, proc_root=tmp_path).collect()[0]
    assert snapshot.cmdline == "tool --token=***"


def test_proc_fallback_is_not_used_when_cmdline_is_legitimately_empty(
    tmp_path: Path,
) -> None:
    """Verifica que un cmdline vacío (hilo de kernel) no dispare lecturas extra."""
    (tmp_path / "3").mkdir()
    (tmp_path / "3" / "cmdline").write_bytes(b"should-not-be-read\0")
    process = FakeProcess(3, cmdline=[])
    snapshot = make_collector(process, proc_root=tmp_path).collect()[0]
    assert snapshot.cmdline is None


def test_cgroup_is_only_read_when_requested(tmp_path: Path) -> None:
    """Verifica que /proc/<pid>/cgroup se lea solo si se solicita."""
    (tmp_path / "3").mkdir()
    (tmp_path / "3" / "cgroup").write_bytes(b"0::/system.slice/x.service\n")
    off = make_collector(FakeProcess(3), proc_root=tmp_path).collect()[0]
    on = make_collector(FakeProcess(3), proc_root=tmp_path, include_cgroup=True)
    assert off.cgroup is None
    assert on.collect()[0].cgroup == "/system.slice/x.service"


def test_missing_cgroup_file_does_not_break_collection(tmp_path: Path) -> None:
    """Verifica que un cgroup inexistente deje el campo en None."""
    collector = make_collector(FakeProcess(3), proc_root=tmp_path, include_cgroup=True)
    assert collector.collect()[0].cgroup is None


def test_home_directory_is_redacted_in_executable_and_cmdline() -> None:
    """Verifica que el directorio personal no aparezca en ejecutable ni cmdline."""
    home = str(Path.home())
    process = FakeProcess(3, exe=f"{home}/bin/tool", cmdline=[f"{home}/bin/tool", "x"])
    snapshot = make_collector(process).collect()[0]
    assert snapshot.executable == "~/bin/tool"
    assert snapshot.cmdline == "~/bin/tool x"


def test_continuous_polling_survives_processes_that_disappear() -> None:
    """Verifica que 300 ciclos con procesos que fallan al azar no lancen excepciones."""
    rng = random.Random(1234)
    errors: list[Callable[[int], BaseException]] = [
        psutil.NoSuchProcess,
        psutil.AccessDenied,
        psutil.ZombieProcess,
        lambda _pid: PermissionError("denegado"),
        lambda _pid: FileNotFoundError("no existe"),
        lambda _pid: ProcessLookupError(),
    ]
    attributes = [
        "ppid", "name", "status", "num_threads", "memory_info", "exe", "cmdline"
    ]

    def factory() -> list[ProcessHandle]:
        processes = []
        for pid in range(40):
            attrs: dict[str, object] = {}
            for attribute in attributes:
                if rng.random() < 0.1:
                    attrs[attribute] = rng.choice(errors)(pid)
            processes.append(FakeProcess(pid, **attrs))
        return list(processes)

    collector = ProcessCollector(process_iter=factory)
    for _ in range(300):
        snapshots = collector.collect()
        stats = collector.last_stats
        assert stats.seen == 40
        assert stats.collected == len(snapshots)
        assert stats.collected + stats.vanished + stats.failed == 40


def test_real_system_collection_includes_current_process() -> None:
    """Verifica la recolección real (psutil) repetida y que incluya este proceso."""
    collector = ProcessCollector(include_cgroup=True)
    for _ in range(3):
        snapshots = collector.collect()
    mine = [item for item in snapshots if item.pid == os.getpid()]
    assert len(mine) == 1
    assert mine[0].name
    assert mine[0].memory_rss_bytes is None or mine[0].memory_rss_bytes > 0
    assert collector.last_stats.collected >= 1


def test_collectors_do_not_run_shell_commands() -> None:
    """Verifica que el código de los collectors no ejecute comandos externos."""
    forbidden = re.compile(r"\bsubprocess\b|os\.system|os\.popen|shell=True")
    for source_file in (APP_DIR / "collectors").rglob("*.py"):
        assert not forbidden.search(source_file.read_text(encoding="utf-8")), source_file


def test_collectors_do_not_modify_processes() -> None:
    """Verifica que el código de los collectors no envíe señales ni modifique procesos."""
    forbidden = re.compile(
        r"\.(kill|terminate|suspend|resume|send_signal|nice|ionice|cpu_affinity)\("
        r"|os\.kill|signal\."
    )
    for source_file in (APP_DIR / "collectors").rglob("*.py"):
        assert not forbidden.search(source_file.read_text(encoding="utf-8")), source_file
