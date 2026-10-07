"""Benchmark del ProcessCollector.

Mide cuánto tarda cada recolección de procesos. Requiere instalar el proyecto
(``pip install -e .``) y solo realiza lecturas.

Uso:
    python scripts/benchmark_process_collector.py --iterations 20
"""

import argparse
import statistics
import time
from collections.abc import Sequence

from app.collectors import ProcessCollector


def run_benchmark(collector: ProcessCollector, iterations: int, warmup: int) -> list[float]:
    """Ejecuta el collector varias veces y mide cada recolección.

    Args:
        collector: Collector a medir.
        iterations: Cantidad de recolecciones medidas.
        warmup: Recolecciones previas descartadas (calientan cachés de psutil).

    Returns:
        Duración de cada recolección medida, en milisegundos.
    """
    for _ in range(warmup):
        collector.collect()
    durations_ms: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        collector.collect()
        durations_ms.append((time.perf_counter() - started) * 1000)
    return durations_ms


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Interpreta los argumentos de línea de comandos.

    Args:
        argv: Argumentos a interpretar; ``None`` usa ``sys.argv``.

    Returns:
        Los argumentos interpretados.
    """
    parser = argparse.ArgumentParser(description="Benchmark del ProcessCollector.")
    parser.add_argument("--iterations", type=int, default=20, help="recolecciones medidas")
    parser.add_argument("--warmup", type=int, default=2, help="recolecciones de calentamiento")
    parser.add_argument("--no-cmdline", action="store_true", help="omite la cmdline")
    parser.add_argument("--cgroup", action="store_true", help="lee /proc/<pid>/cgroup")
    parser.add_argument("--username", action="store_true", help="consulta el usuario")
    args = parser.parse_args(argv)
    if args.iterations < 1 or args.warmup < 0:
        parser.error("--iterations debe ser >= 1 y --warmup >= 0")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta el benchmark e imprime un resumen.

    Args:
        argv: Argumentos de línea de comandos; ``None`` usa ``sys.argv``.

    Returns:
        Código de salida del proceso (0 indica éxito).
    """
    args = parse_args(argv)
    collector = ProcessCollector(
        include_cmdline=not args.no_cmdline,
        include_cgroup=args.cgroup,
        include_username=args.username,
    )
    durations_ms = run_benchmark(collector, args.iterations, args.warmup)
    stats = collector.last_stats
    mean_ms = statistics.fmean(durations_ms)
    p95_ms = sorted(durations_ms)[min(len(durations_ms) - 1, int(len(durations_ms) * 0.95))]
    print(f"Procesos vistos: {stats.seen} (leídos: {stats.collected}, "
          f"desaparecidos: {stats.vanished}, con error: {stats.failed})")
    print(f"Iteraciones: {args.iterations} (calentamiento: {args.warmup})")
    print(f"Tiempo por recolección: media {mean_ms:.1f} ms | "
          f"mediana {statistics.median(durations_ms):.1f} ms | "
          f"p95 {p95_ms:.1f} ms | mín {min(durations_ms):.1f} ms | "
          f"máx {max(durations_ms):.1f} ms")
    if stats.collected:
        print(f"Costo medio por proceso: {mean_ms * 1000 / stats.collected:.1f} µs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
