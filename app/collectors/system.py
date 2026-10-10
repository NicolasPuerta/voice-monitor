"""Collectors de mtricas del sistema."""

import time
import psutil
from pathlib import Path
from typing import Tuple

from app.collectors.base import Collector
from app.collectors.health import SourceHealthManager, SourceState
from app.domain.snapshots import (
    PressureStall,
    ResourceSnapshot,
    SystemPressure,
)

DEFAULT_PROC_ROOT = Path("/proc")
DEFAULT_SYS_ROOT = Path("/sys")


class SystemResourceCollector(Collector[ResourceSnapshot]):
    """Recolecta mtricas generales de recursos usando psutil."""

    def __init__(self, health_manager: SourceHealthManager) -> None:
        self._health_manager = health_manager

    @property
    def name(self) -> str:
        return "system_resources"

    def collect(self) -> ResourceSnapshot:
        try:
            cpu_percent = psutil.cpu_percent()
            cpu_count = psutil.cpu_count() or 1

            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()

            try:
                load_avg = psutil.getloadavg()
            except (AttributeError, NotImplementedError, OSError):
                load_avg = None

            snapshot = ResourceSnapshot(
                cpu_percent=cpu_percent,
                cpu_count_logical=cpu_count,
                load_average=load_avg,
                memory_total_bytes=mem.total,
                memory_used_bytes=mem.used,
                memory_available_bytes=mem.available,
                memory_percent=mem.percent,
                swap_total_bytes=swap.total,
                swap_used_bytes=swap.used,
                swap_percent=swap.percent,
            )
            self._health_manager.set_state(self.name, SourceState.OK)
            return snapshot
        except Exception as e:
            self._health_manager.set_state(self.name, SourceState.DEGRADED, str(e))
            # Retornar un snapshot vaco o con ceros en caso de fallo catastrfico
            # para no detener el agente.
            return ResourceSnapshot(
                cpu_percent=0.0,
                cpu_count_logical=1,
                memory_total_bytes=0,
                memory_used_bytes=0,
                memory_available_bytes=0,
                memory_percent=0.0,
            )

    def get_uptime(self) -> float:
        """Obtiene el tiempo de actividad del sistema en segundos."""
        try:
            return time.time() - psutil.boot_time()
        except Exception:
            return 0.0


class PSICollector(Collector[SystemPressure]):
    """Recolecta mtricas PSI (Pressure Stall Information) en Linux."""

    def __init__(
        self,
        health_manager: SourceHealthManager,
        proc_root: Path = DEFAULT_PROC_ROOT,
    ) -> None:
        self._health_manager = health_manager
        self._proc_root = proc_root

    @property
    def name(self) -> str:
        return "psi"

    def collect(self) -> SystemPressure:
        cpu_some, _ = self._parse_psi_file(self._proc_root / "pressure" / "cpu")
        mem_some, mem_full = self._parse_psi_file(self._proc_root / "pressure" / "memory")
        io_some, io_full = self._parse_psi_file(self._proc_root / "pressure" / "io")

        if cpu_some is None and mem_some is None and io_some is None:
            self._health_manager.set_state(
                self.name,
                SourceState.DISABLED,
                "PSI files are missing or unreadable.",
            )
        else:
            self._health_manager.set_state(self.name, SourceState.OK)

        return SystemPressure(
            cpu_some=cpu_some,
            memory_some=mem_some,
            memory_full=mem_full,
            io_some=io_some,
            io_full=io_full,
        )

    def _parse_psi_file(
        self, path: Path
    ) -> Tuple[PressureStall | None, PressureStall | None]:
        some_stall = None
        full_stall = None
        try:
            content = path.read_text(encoding="utf-8")
            for line in content.splitlines():
                parts = line.split()
                if not parts:
                    continue
                prefix = parts[0]
                avg10 = avg60 = avg300 = 0.0
                for part in parts[1:]:
                    if part.startswith("avg10="):
                        avg10 = float(part.split("=")[1])
                    elif part.startswith("avg60="):
                        avg60 = float(part.split("=")[1])
                    elif part.startswith("avg300="):
                        avg300 = float(part.split("=")[1])
                stall = PressureStall(avg10=avg10, avg60=avg60, avg300=avg300)
                if prefix == "some":
                    some_stall = stall
                elif prefix == "full":
                    full_stall = stall
        except (FileNotFoundError, PermissionError, IsADirectoryError):
            pass
        except Exception:
            # Invalid format
            pass
        return some_stall, full_stall


class EnergyStateCollector(Collector[Tuple[float | None, bool | None]]):
    """Detecta el estado de la batera en Linux de forma agnstica al hardware."""

    def __init__(
        self,
        health_manager: SourceHealthManager,
        sys_root: Path = DEFAULT_SYS_ROOT,
    ) -> None:
        self._health_manager = health_manager
        self._sys_root = sys_root

    @property
    def name(self) -> str:
        return "energy"

    def collect(self) -> Tuple[float | None, bool | None]:
        """Devuelve una tupla con (battery_percent, battery_plugged)."""
        power_supply_dir = self._sys_root / "class" / "power_supply"

        battery_percent: float | None = None
        battery_plugged: bool | None = None

        if not power_supply_dir.is_dir():
            self._health_manager.set_state(
                self.name,
                SourceState.DISABLED,
                "/sys/class/power_supply/ no encontrado.",
            )
            return None, None

        has_sensors = False
        try:
            for supply in power_supply_dir.iterdir():
                type_file = supply / "type"
                if not type_file.is_file():
                    continue

                has_sensors = True
                supply_type = type_file.read_text(encoding="utf-8").strip()

                if supply_type == "Battery":
                    cap_file = supply / "capacity"
                    status_file = supply / "status"

                    if cap_file.is_file():
                        try:
                            battery_percent = float(
                                cap_file.read_text(encoding="utf-8").strip()
                            )
                        except ValueError:
                            pass

                    if status_file.is_file():
                        status = status_file.read_text(encoding="utf-8").strip()
                        if status in ("Charging", "Full"):
                            battery_plugged = True
                        elif status == "Discharging":
                            battery_plugged = False

                elif supply_type == "Mains":
                    online_file = supply / "online"
                    if online_file.is_file():
                        try:
                            battery_plugged = bool(
                                int(online_file.read_text(encoding="utf-8").strip())
                            )
                        except ValueError:
                            pass
        except (PermissionError, FileNotFoundError):
            self._health_manager.set_state(
                self.name,
                SourceState.DEGRADED,
                "Permisos insuficientes o fallos de lectura.",
            )
            return battery_percent, battery_plugged
        except Exception as e:
            self._health_manager.set_state(self.name, SourceState.DEGRADED, str(e))
            return battery_percent, battery_plugged

        if not has_sensors:
            self._health_manager.set_state(
                self.name, SourceState.DISABLED, "No hay sensores de energa."
            )
        else:
            self._health_manager.set_state(self.name, SourceState.OK)

        return battery_percent, battery_plugged
