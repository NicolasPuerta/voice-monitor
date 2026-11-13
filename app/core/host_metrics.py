"""Métricas del equipo para el informe HTML (instantánea y series por minuto)."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import platform
import socket
from typing import Any

import psutil

logger = logging.getLogger(__name__)

CHART_W = 640
CHART_H = 150
PAD_L = 36
PAD_R = 10
PAD_T = 10
PAD_B = 22


def format_bytes(value: float) -> str:
    """Formatea bytes en una unidad legible (GB, MB, ...)."""
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def format_uptime(seconds: float) -> str:
    """Formatea segundos como ``Xd Yh Zm``."""
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    parts = [f"{days}d"] if days else []
    parts += [f"{hours}h", f"{minutes}m"]
    return " ".join(parts)


def _distro() -> str:
    try:
        return str(platform.freedesktop_os_release().get("PRETTY_NAME", "Linux"))
    except (OSError, AttributeError):
        return platform.system()


def collect_host_metrics() -> dict[str, Any]:
    """Lee una instantánea del equipo. Cada bloque falla de forma independiente."""
    info: list[tuple[str, str]] = []
    gauges: list[dict[str, Any]] = []
    top_memory: list[dict[str, str]] = []

    def safe(label: str, func: Any) -> None:
        try:
            func()
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Métrica '%s' no disponible: %s", label, exc)

    def _system() -> None:
        info.append(("Equipo", socket.gethostname()))
        info.append(("Sistema", _distro()))
        info.append(("Kernel", platform.release()))
        info.append(("Arquitectura", platform.machine()))

    def _cpu() -> None:
        logical = psutil.cpu_count(logical=True) or 0
        physical = psutil.cpu_count(logical=False)
        cores = f"{logical} lógicos" + (f" / {physical} físicos" if physical else "")
        info.append(("Núcleos", cores))
        percent = psutil.cpu_percent(interval=0.2)
        gauges.append(
            {"label": "CPU", "percent": round(percent, 1), "detail": cores}
        )
        load1, load5, load15 = os.getloadavg()
        info.append(("Carga (1/5/15 min)", f"{load1:.2f} / {load5:.2f} / {load15:.2f}"))

    def _memory() -> None:
        mem = psutil.virtual_memory()
        gauges.append(
            {
                "label": "Memoria",
                "percent": round(mem.percent, 1),
                "detail": f"{format_bytes(mem.used)} de {format_bytes(mem.total)}",
            }
        )
        swap = psutil.swap_memory()
        if swap.total:
            gauges.append(
                {
                    "label": "Swap",
                    "percent": round(swap.percent, 1),
                    "detail": f"{format_bytes(swap.used)} de {format_bytes(swap.total)}",
                }
            )

    def _disk() -> None:
        disk = psutil.disk_usage("/")
        gauges.append(
            {
                "label": "Disco (/)",
                "percent": round(disk.percent, 1),
                "detail": f"{format_bytes(disk.used)} de {format_bytes(disk.total)}",
            }
        )

    def _uptime() -> None:
        info.append(("Tiempo encendido", format_uptime(
            datetime.now(timezone.utc).timestamp() - psutil.boot_time()
        )))

    def _battery() -> None:
        battery = psutil.sensors_battery()
        if battery is not None:
            state = "cargando" if battery.power_plugged else "en batería"
            info.append(("Batería", f"{battery.percent:.0f}% ({state})"))

    def _top() -> None:
        procs = []
        for proc in psutil.process_iter(["name", "memory_info"]):
            mem_info = proc.info.get("memory_info")
            if mem_info is not None:
                procs.append((mem_info.rss, proc.info.get("name") or "?"))
        for rss, name in sorted(procs, reverse=True)[:5]:
            top_memory.append({"name": str(name), "rss": format_bytes(rss)})

    for label, func in (
        ("sistema", _system),
        ("cpu", _cpu),
        ("memoria", _memory),
        ("disco", _disk),
        ("uptime", _uptime),
        ("batería", _battery),
        ("procesos", _top),
    ):
        safe(label, func)

    return {
        "captured_at": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
        "info": info,
        "gauges": gauges,
        "top_memory": top_memory,
    }


def build_line_chart(
    points: list[tuple[str, float, float]], color: str = "#2563eb"
) -> str:
    """Genera un gráfico SVG (promedio y máximo por minuto, escala 0-100 %).

    Args:
        points: Lista de ``(timestamp_iso, promedio, máximo)`` ordenada.
        color: Color de la línea del promedio.

    Returns:
        SVG como cadena; vacía si hay menos de dos puntos.
    """
    if len(points) < 2:
        return ""
    inner_w = CHART_W - PAD_L - PAD_R
    inner_h = CHART_H - PAD_T - PAD_B

    def xy(index: int, value: float) -> tuple[float, float]:
        x = PAD_L + inner_w * index / (len(points) - 1)
        clamped = max(0.0, min(100.0, value))
        return x, PAD_T + inner_h * (1 - clamped / 100)

    def path(values: list[float]) -> str:
        return " ".join(
            f"{x:.1f},{y:.1f}" for x, y in (xy(i, v) for i, v in enumerate(values))
        )

    avg_pts = path([p[1] for p in points])
    max_pts = path([p[2] for p in points])
    base_y = PAD_T + inner_h
    area = f"{PAD_L:.1f},{base_y:.1f} {avg_pts} {PAD_L + inner_w:.1f},{base_y:.1f}"

    grid = []
    for pct in (0, 50, 100):
        _, y = xy(0, pct)
        grid.append(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{CHART_W - PAD_R}" y2="{y:.1f}" '
            f'stroke="#e2e8f0" stroke-width="1"/>'
            f'<text x="{PAD_L - 4}" y="{y + 3:.1f}" text-anchor="end" '
            f'font-size="9" fill="#64748b">{pct}%</text>'
        )

    def label(ts: str) -> str:
        try:
            return datetime.fromisoformat(ts).strftime("%H:%M")
        except ValueError:
            return ""

    return (
        f'<svg viewBox="0 0 {CHART_W} {CHART_H}" width="100%" role="img" '
        f'xmlns="http://www.w3.org/2000/svg" style="max-width:{CHART_W}px">'
        + "".join(grid)
        + f'<polygon points="{area}" fill="{color}" fill-opacity="0.12"/>'
        f'<polyline points="{max_pts}" fill="none" stroke="#dc2626" '
        f'stroke-width="1" stroke-dasharray="3,3"/>'
        f'<polyline points="{avg_pts}" fill="none" stroke="{color}" '
        f'stroke-width="2"/>'
        f'<text x="{PAD_L}" y="{CHART_H - 6}" font-size="9" fill="#64748b">'
        f"{label(points[0][0])}</text>"
        f'<text x="{CHART_W - PAD_R}" y="{CHART_H - 6}" text-anchor="end" '
        f'font-size="9" fill="#64748b">{label(points[-1][0])}</text>'
        "</svg>"
    )
