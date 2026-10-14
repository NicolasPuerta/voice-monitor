"""Métricas de rendimiento y consumo de recursos del agente."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import os
import statistics
import time
from typing import Any, Iterator

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]

from app.domain.enums import EventDecision
from app.domain.events import Event


@dataclass
class TimingStats:
    """Estadísticas agregadas de tiempos de ejecución en milisegundos."""

    count: int = 0
    total_ms: float = 0.0
    avg_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    p95_ms: float = 0.0

    @classmethod
    def from_samples(cls, samples: list[float]) -> "TimingStats":
        if not samples:
            return cls()
        cnt = len(samples)
        tot = sum(samples)
        avg = tot / cnt
        mn = min(samples)
        mx = max(samples)
        if cnt == 1:
            p95 = samples[0]
        else:
            s_sorted = sorted(samples)
            idx = int(round(0.95 * (cnt - 1)))
            p95 = s_sorted[min(idx, cnt - 1)]
        return cls(
            count=cnt,
            total_ms=round(tot, 3),
            avg_ms=round(avg, 3),
            min_ms=round(mn, 3),
            max_ms=round(mx, 3),
            p95_ms=round(p95, 3),
        )


@dataclass
class ResourceSample:
    """Muestra del uso de CPU y memoria RAM del proceso del agente."""

    timestamp: float
    cpu_percent: float
    ram_rss_mb: float


class PerformanceMetrics:
    """Recolector de métricas de consumo de recursos y latencias."""

    def __init__(self) -> None:
        self._proc = psutil.Process(os.getpid()) if psutil is not None else None
        # Inicializar medición de CPU de psutil
        if self._proc is not None:
            try:
                self._proc.cpu_percent(interval=None)
            except Exception:
                pass

        self._collector_times: dict[str, list[float]] = {}
        self._scoring_times: list[float] = []
        self._event_latencies_ms: list[float] = []
        self._gemini_times: list[float] = []
        self._audio_synthesis_times: list[float] = []
        self._audio_playback_times: list[float] = []
        self._resource_samples: list[ResourceSample] = []

        self._counters: dict[str, int] = {
            "events_detected": 0,
            "events_scored": 0,
            "events_spoken": 0,
            "events_deferred": 0,
            "events_threshold_omitted": 0,
            "events_dnd": 0,
            "events_expired": 0,
        }

    @contextmanager
    def measure_collector(self, name: str) -> Iterator[None]:
        """Context manager para medir la duración de un collector en ms."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self._collector_times.setdefault(name, []).append(elapsed_ms)

    @contextmanager
    def measure_scoring(self) -> Iterator[None]:
        """Context manager para medir el tiempo del motor de scoring en ms."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self._scoring_times.append(elapsed_ms)

    @contextmanager
    def measure_gemini(self) -> Iterator[None]:
        """Context manager para medir la llamada de Gemini en ms."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self._gemini_times.append(elapsed_ms)

    @contextmanager
    def measure_audio_synthesis(self) -> Iterator[None]:
        """Context manager para medir la síntesis de audio en ms."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self._audio_synthesis_times.append(elapsed_ms)

    @contextmanager
    def measure_audio_playback(self) -> Iterator[None]:
        """Context manager para medir la reproducción de audio en ms."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self._audio_playback_times.append(elapsed_ms)

    def record_event_latency(self, event: Event, now: datetime) -> float:
        """Registra la latencia desde detected_at hasta el momento actual."""
        latency_ms = max(0.0, (now - event.detected_at).total_seconds() * 1000.0)
        self._event_latencies_ms.append(latency_ms)
        return latency_ms

    def record_decision(self, decision: EventDecision | None) -> None:
        """Incrementa el contador de la decisión tomada."""
        if decision == EventDecision.SPOKEN:
            self._counters["events_spoken"] += 1
        elif decision == EventDecision.DEFERRED:
            self._counters["events_deferred"] += 1
        elif decision == EventDecision.THRESHOLD_OMITTED:
            self._counters["events_threshold_omitted"] += 1
        elif decision == EventDecision.DND:
            self._counters["events_dnd"] += 1
        elif decision == EventDecision.EXPIRED:
            self._counters["events_expired"] += 1

    def increment_counter(self, name: str, value: int = 1) -> None:
        """Incrementa un contador arbitrario."""
        self._counters[name] = self._counters.get(name, 0) + value

    def sample_resources(self) -> tuple[float, float]:
        """Muestrea el consumo de CPU % y RAM RSS (MB) del agente."""
        cpu_pct = 0.0
        ram_mb = 0.0
        if self._proc is not None:
            try:
                # cpu_percent no bloqueante
                cpu_pct = round(self._proc.cpu_percent(interval=None), 2)
                mem_info = self._proc.memory_info()
                ram_mb = round(mem_info.rss / (1024.0 * 1024.0), 2)
            except Exception:
                pass
        sample = ResourceSample(
            timestamp=time.time(),
            cpu_percent=cpu_pct,
            ram_rss_mb=ram_mb,
        )
        self._resource_samples.append(sample)
        return cpu_pct, ram_mb

    def get_summary(self) -> dict[str, Any]:
        """Genera un resumen completo con estadísticas agregadas."""
        collectors_summary = {
            name: TimingStats.from_samples(samples)
            for name, samples in self._collector_times.items()
        }

        # Resumen de recursos
        cpu_samples = [s.cpu_percent for s in self._resource_samples]
        ram_samples = [s.ram_rss_mb for s in self._resource_samples]

        avg_cpu = round(statistics.mean(cpu_samples), 2) if cpu_samples else 0.0
        max_cpu = round(max(cpu_samples), 2) if cpu_samples else 0.0
        avg_ram = round(statistics.mean(ram_samples), 2) if ram_samples else 0.0
        max_ram = round(max(ram_samples), 2) if ram_samples else 0.0

        return {
            "resources": {
                "avg_cpu_percent": avg_cpu,
                "max_cpu_percent": max_cpu,
                "target_cpu_percent": 2.0,
                "cpu_target_met": avg_cpu <= 2.0,
                "avg_ram_mb": avg_ram,
                "max_ram_mb": max_ram,
                "target_ram_mb": 100.0,
                "ram_target_met": max_ram <= 100.0,
                "sample_count": len(self._resource_samples),
            },
            "collectors": collectors_summary,
            "scoring": TimingStats.from_samples(self._scoring_times),
            "latency": TimingStats.from_samples(self._event_latencies_ms),
            "gemini": TimingStats.from_samples(self._gemini_times),
            "audio_synthesis": TimingStats.from_samples(self._audio_synthesis_times),
            "audio_playback": TimingStats.from_samples(self._audio_playback_times),
            "counters": dict(self._counters),
        }

    def reset(self) -> None:
        """Reinicia las métricas acumuladas."""
        self._collector_times.clear()
        self._scoring_times.clear()
        self._event_latencies_ms.clear()
        self._gemini_times.clear()
        self._audio_synthesis_times.clear()
        self._audio_playback_times.clear()
        self._resource_samples.clear()
        for k in self._counters:
            self._counters[k] = 0
