"""Construcción del contexto del sistema combinando métricas y agrupando aplicaciones."""

from datetime import datetime, timezone
from typing import Iterable

from app.collectors.health import SourceHealthManager
from app.domain.context import ApplicationGroup, SystemContext
from app.domain.journald import JournaldSnapshot
from app.domain.risk import RiskSignal
from app.domain.snapshots import ProcessSnapshot, ResourceSnapshot, SystemPressure
from app.domain.systemd import SystemdSnapshot

SHELLS_AND_TERMINALS = {
    "bash",
    "zsh",
    "fish",
    "sh",
    "dash",
    "tmux",
    "screen",
    "sshd",
    "gnome-terminal-server",
    "konsole",
    "alacritty",
    "kitty",
    "xterm",
}

INTERPRETERS = {"python", "python3", "node", "nodejs", "java", "ruby", "perl"}


class SystemContextBuilder:
    """Combina snapshots dispares en una vista estructurada y agrupa aplicaciones."""

    def __init__(self) -> None:
        pass

    def build(
        self,
        *,
        collected_at: datetime | None = None,
        resources: ResourceSnapshot | None = None,
        pressure: SystemPressure | None = None,
        uptime_s: float | None = None,
        processes: Iterable[ProcessSnapshot] | None = None,
        health_manager: SourceHealthManager | None = None,
        systemd: SystemdSnapshot | None = None,
        journald: JournaldSnapshot | None = None,
        risk_signals: tuple[RiskSignal, ...] = (),
    ) -> SystemContext:
        """Agrupa los procesos y construye el SystemContext."""
        if collected_at is None:
            collected_at = datetime.now(timezone.utc)

        if health_manager is None:
            health_manager = SourceHealthManager()

        if resources is None:
            try:
                from app.collectors.system import SystemResourceCollector

                sys_coll = SystemResourceCollector(health_manager)
                resources = sys_coll.collect()
                uptime_s = sys_coll.get_uptime()
            except Exception:
                resources = ResourceSnapshot(
                    cpu_percent=0.0,
                    cpu_count_logical=1,
                    memory_total_bytes=1000,
                    memory_used_bytes=500,
                    memory_available_bytes=500,
                    memory_percent=50.0,
                )

        if processes is None:
            try:
                from app.collectors.process import ProcessCollector

                proc_coll = ProcessCollector()
                processes = proc_coll.collect()
            except Exception:
                processes = []

        apps = self._group_processes(processes)

        health_states = {
            "system_resources": health_manager.get_state("system_resources").value,
            "psi": health_manager.get_state("psi").value,
            "energy": health_manager.get_state("energy").value,
            "process": health_manager.get_state("process").value,
        }
        for s_name, s_state in health_manager.get_all_states().items():
            health_states[s_name] = s_state.value

        return SystemContext(
            collected_at=collected_at,
            resources=resources,
            pressure=pressure,
            uptime_s=uptime_s,
            apps=tuple(apps),
            source_health=health_states,
            systemd=systemd,
            journald=journald,
            risk_signals=risk_signals,
        )

    def _group_processes(
        self, processes: Iterable[ProcessSnapshot]
    ) -> list[ApplicationGroup]:
        pid_to_proc = {p.pid: p for p in processes}
        groups: dict[str, list[ProcessSnapshot]] = {}
        root_map: dict[int, ProcessSnapshot] = {}

        # 1. Encontrar la raíz lógica de cada proceso
        for p in pid_to_proc.values():
            root = self._find_app_root(p, pid_to_proc)
            root_map[p.pid] = root

        # 2. Generar llaves para cada raíz y agrupar
        for p in pid_to_proc.values():
            root = root_map[p.pid]
            app_key = self._generate_app_key(root)
            groups.setdefault(app_key, []).append(p)

        # 3. Construir los modelos ApplicationGroup
        app_groups = []
        for app_key, procs in groups.items():
            # Buscar el proceso raíz del grupo para extraer el nombre
            # Múltiples árboles podrían compartir la misma llave (e.g. dos 'bash')
            # Usamos el primer proceso como representativo o el que generó la llave
            root_candidates = [root_map[p.pid] for p in procs]
            representative_root = root_candidates[0] if root_candidates else procs[0]

            name = self._generate_app_name(representative_root)

            total_cpu = round(sum(p.cpu_percent for p in procs), 2)
            total_rss = sum((p.memory_rss_bytes or 0) for p in procs)

            # Ordenar por uso de CPU para que los más pesados estén primero
            procs_sorted = sorted(procs, key=lambda x: x.cpu_percent, reverse=True)

            app_groups.append(
                ApplicationGroup(
                    app_key=app_key,
                    name=name,
                    processes=tuple(procs_sorted),
                    cpu_percent=total_cpu,
                    memory_rss_bytes=total_rss,
                )
            )

        # Ordenar grupos por uso de CPU descendente
        app_groups.sort(key=lambda g: g.cpu_percent, reverse=True)
        return app_groups

    def _find_app_root(
        self, process: ProcessSnapshot, pid_to_proc: dict[int, ProcessSnapshot]
    ) -> ProcessSnapshot:
        seen = set()
        current = process.pid

        while current in pid_to_proc and current not in seen:
            seen.add(current)
            p = pid_to_proc[current]

            # Init o systemd
            if p.parent_pid in (0, 1, 2):
                break

            parent = pid_to_proc.get(p.parent_pid)  # type: ignore[arg-type]
            if not parent:
                break

            # Separación lógica: shell o terminal
            if parent.name in SHELLS_AND_TERMINALS:
                break

            # Separación por cgroup explícito (ej. salto de user.slice a app.slice)
            if p.cgroup and parent.cgroup and p.cgroup != parent.cgroup:
                break

            current = p.parent_pid  # type: ignore[assignment]

        return pid_to_proc[current] if current in pid_to_proc else process

    def _generate_app_key(self, root: ProcessSnapshot) -> str:
        if root.cgroup and (
            "app-" in root.cgroup or ".service" in root.cgroup or "docker" in root.cgroup
        ):
            return f"cgroup:{root.cgroup}"

        if root.name in INTERPRETERS:
            if root.cmdline:
                # El cmdline está sanitizado y no contiene secretos
                return f"cmd:{root.cmdline}"

        if root.executable:
            return f"exe:{root.executable}"

        return f"name:{root.name}"

    def _generate_app_name(self, root: ProcessSnapshot) -> str:
        if root.name in INTERPRETERS:
            if root.cmdline:
                parts = root.cmdline.split()
                if len(parts) > 1:
                    script = parts[1].split("/")[-1]
                    return f"{root.name} ({script})"

        if root.cgroup and "app-gnome-" in root.cgroup:
            # e.g., /user.slice/app-gnome-firefox-12345.scope
            scope_part = root.cgroup.split("/")[-1]
            parts = scope_part.split("-")
            for part in parts:
                if part not in ("app", "gnome") and not part.endswith(".scope"):
                    return part.replace(".scope", "")
            return "gnome-app"

        if root.executable:
            return root.executable.split("/")[-1]

        return root.name
