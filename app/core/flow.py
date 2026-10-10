"""Controlador de flujo, agrupacin y colas de prioridad para eventos."""

import heapq
from datetime import datetime

from app.domain.enums import EventDecision, EventPriority
from app.domain.events import Event
from app.core.scoring import ScoringEngine


class EventGrouper:
    """Agrupa y de-duplica eventos en una ventana temporal (coalescing)."""

    def __init__(self, window_s: float = 3.0) -> None:
        self.window_s = window_s
        self._buffer: dict[str, Event] = {}
        self._window_start: datetime | None = None

    def add(self, event: Event, now: datetime) -> None:
        if self._window_start is None:
            self._window_start = now

        # Clave de agrupacin: tipo de evento + llave de aplicacin
        app_key = event.metadata.app_key or "system"
        key = f"{event.event_type.value}:{app_key}"

        # Deduplicacin: conservar el evento de mayor severidad
        if key in self._buffer:
            existing = self._buffer[key]
            # Podramos comparar severidades. Por simplicidad, reemplazamos
            # si el nuevo tiene mayor severidad (usamos el orden del enum hackeado o if)
            # Para simplificar, nos quedamos con el ms reciente o el de mayor valor
            if event.metadata.metric_value and existing.metadata.metric_value:
                if event.metadata.metric_value > existing.metadata.metric_value:
                    self._buffer[key] = event
            else:
                self._buffer[key] = event
        else:
            self._buffer[key] = event

    def should_flush(self, now: datetime) -> bool:
        if self._window_start is None:
            return False
        return (now - self._window_start).total_seconds() >= self.window_s

    def flush(self) -> list[Event]:
        events = list(self._buffer.values())
        self._buffer.clear()
        self._window_start = None
        return events


class PriorityQueue:
    """Cola de prioridad con TTL."""

    def __init__(self, ttl_s: float = 30.0) -> None:
        self.ttl_s = ttl_s
        self._queue: list[tuple[float, int, Event]] = []
        self._counter = 0

    def push(self, event: Event) -> None:
        if not event.score_result:
            return

        # heapq es min-heap, usamos score negativo para que salga el mayor
        score = event.score_result.score
        self._counter += 1
        heapq.heappush(self._queue, (-score, self._counter, event))

    def pop_ready(self, now: datetime) -> Event | None:
        self._evict_expired(now)
        if not self._queue:
            return None
        _, _, event = heapq.heappop(self._queue)
        return event

    def peek_highest_priority(self) -> EventPriority | None:
        if not self._queue:
            return None
        _, _, event = self._queue[0]
        return event.score_result.priority if event.score_result else None

    def _evict_expired(self, now: datetime) -> None:
        active = []
        for neg_score, cnt, event in self._queue:
            age = (now - event.detected_at).total_seconds()
            if age > self.ttl_s:
                event.decision = EventDecision.EXPIRED
            else:
                active.append((neg_score, cnt, event))

        if len(active) != len(self._queue):
            heapq.heapify(active)
            self._queue = active


class FlowController:
    """Controla cundo se puede reproducir un evento basndose en token bucket."""

    def __init__(self, scoring_engine: ScoringEngine) -> None:
        self.scoring_engine = scoring_engine

        self.burst_limit = 3
        self.regen_interval_s = 8.0
        # Presupuesto inicial (ej. ~10 segundos de habla representados en 3 tokens)
        self.tokens = 3.0

        self.last_regen_time: datetime | None = None
        self.last_spoken_time: datetime | None = None

        # Cooldown global (mnimo tiempo entre cualquier interaccin)
        self.cooldown_s = 2.0

    def _regen_tokens(self, now: datetime) -> None:
        if self.last_regen_time is None:
            self.last_regen_time = now
            return

        elapsed = (now - self.last_regen_time).total_seconds()
        added = elapsed / self.regen_interval_s
        if added > 0:
            self.tokens = min(float(self.burst_limit), self.tokens + added)
            self.last_regen_time = now

    def process_queue(self, queue: PriorityQueue, now: datetime) -> Event | None:
        """Extrae el mejor evento de la cola si el flujo lo permite."""
        self._regen_tokens(now)

        # Comprobar cooldown global
        if self.last_spoken_time is not None:
            if (now - self.last_spoken_time).total_seconds() < self.cooldown_s:
                # No podemos hablar todava por el cooldown fsico
                return None

        highest_priority = queue.peek_highest_priority()
        if not highest_priority:
            return None

        # Evaluamos preemption para CRITICAL
        can_speak = False
        if highest_priority == EventPriority.CRITICAL:
            # Los críticos saltan el token bucket pero se les cobra (pueden endeudarse)
            can_speak = True
        elif self.tokens >= 1.0:
            can_speak = True

        if can_speak:
            event = queue.pop_ready(now)
            if not event:
                return None

            # Restamos token y actualizamos tracking
            self.tokens -= 1.0
            self.last_spoken_time = now

            event.decision = EventDecision.SPOKEN
            self.scoring_engine.record_spoken(event, now)
            return event
        else:
            # Si no hay tokens, eventos normales se posponen
            # (Quedan en la cola como DEFERRED hasta que haya tokens o expiren)
            # DND podría aplicarse si estamos en un modo "No molestar".
            # Por ahora se mantienen en cola.
            return None
