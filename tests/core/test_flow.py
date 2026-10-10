"""Pruebas del motor de puntuacin y control de flujo de eventos."""

from datetime import datetime, timedelta, timezone

from app.core.flow import EventGrouper, FlowController, PriorityQueue
from app.core.scoring import ScoringEngine
from app.domain.enums import EventDecision, EventPriority, EventSeverity, EventType
from app.domain.events import Event, EventMetadata

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_test_event(
    severity: EventSeverity, duration_s: float, app_name: str, app_key: str
) -> Event:
    return Event(
        event_type=EventType.CPU_SPIKE,
        severity=severity,
        summary="Test",
        detected_at=NOW,
        metadata=EventMetadata(app_name=app_name, app_key=app_key, duration_s=duration_s),
    )


def test_scoring_engine_priorities() -> None:
    engine = ScoringEngine()

    # Evento crtico
    ev_crit = make_test_event(EventSeverity.CRITICAL, 2.0, "system", "system")
    res_crit = engine.score_event(ev_crit, NOW)
    assert res_crit.priority == EventPriority.CRITICAL
    assert res_crit.score >= 30.0

    # Evento de usuario (Firefox, alta relevancia) + reciente (alta novedad)
    ev_high = make_test_event(EventSeverity.HIGH, 2.0, "firefox", "cgroup:/app.slice")
    res_high = engine.score_event(ev_high, NOW)
    assert res_high.priority in (EventPriority.HIGH, EventPriority.CRITICAL)
    assert res_high.breakdown.relevance == 20.0
    assert res_high.breakdown.novelty == 15.0


def test_scoring_repetition_penalty() -> None:
    engine = ScoringEngine()
    ev = make_test_event(EventSeverity.MEDIUM, 30.0, "bash", "exe:/bin/bash")

    # Primera vez: sin penalizacin
    res1 = engine.score_event(ev, NOW)
    assert res1.breakdown.repetition_penalty == 0.0

    # Lo simulamos como hablado
    engine.record_spoken(ev, NOW)

    # Segunda vez: penalizacin
    res2 = engine.score_event(ev, NOW)
    assert res2.breakdown.repetition_penalty == 15.0
    assert res2.score < res1.score


def test_event_grouper_coalescing() -> None:
    grouper = EventGrouper(window_s=3.0)

    ev1 = make_test_event(EventSeverity.MEDIUM, 10.0, "firefox", "app1")
    ev1.metadata.metric_value = 50.0
    grouper.add(ev1, NOW)

    assert not grouper.should_flush(NOW + timedelta(seconds=1.0))

    # Mismo app_key, debera de-duplicar y quedarse con el de mayor mtrica
    ev2 = make_test_event(EventSeverity.MEDIUM, 10.0, "firefox", "app1")
    ev2.metadata.metric_value = 80.0
    grouper.add(ev2, NOW + timedelta(seconds=1.5))

    # Distinto app_key
    ev3 = make_test_event(EventSeverity.MEDIUM, 10.0, "bash", "app2")
    grouper.add(ev3, NOW + timedelta(seconds=2.0))

    assert grouper.should_flush(NOW + timedelta(seconds=3.1))
    events = grouper.flush()

    assert len(events) == 2
    firefox_ev = next(e for e in events if e.metadata.app_key == "app1")
    assert firefox_ev.metadata.metric_value == 80.0


def test_priority_queue_ordering_and_ttl() -> None:
    queue = PriorityQueue(ttl_s=30.0)
    engine = ScoringEngine()

    ev_normal = make_test_event(EventSeverity.LOW, 100.0, "bash", "bash")
    ev_normal.score_result = engine.score_event(ev_normal, NOW)

    ev_high = make_test_event(EventSeverity.HIGH, 2.0, "firefox", "ff")
    ev_high.score_result = engine.score_event(ev_high, NOW)

    queue.push(ev_normal)
    queue.push(ev_high)

    # Pop debe devolver el de mayor score primero
    out1 = queue.pop_ready(NOW)
    assert out1 == ev_high

    # Simulamos que pasa el tiempo
    future = NOW + timedelta(seconds=35.0)
    out2 = queue.pop_ready(future)
    assert out2 is None
    assert ev_normal.decision == EventDecision.EXPIRED


def test_flow_controller_token_bucket_and_preemption() -> None:
    engine = ScoringEngine()
    flow = FlowController(engine)
    queue = PriorityQueue()

    # Evento crtico y 4 eventos normales (para saturar el burst de 3)
    ev_crit = make_test_event(EventSeverity.CRITICAL, 1.0, "sys", "sys")
    ev_crit.score_result = engine.score_event(ev_crit, NOW)

    normals = []
    for i in range(4):
        ev = make_test_event(EventSeverity.MEDIUM, 10.0, f"app{i}", f"app{i}")
        ev.score_result = engine.score_event(ev, NOW)
        normals.append(ev)
        queue.push(ev)

    # Inicialmente tenemos 3 tokens. Se consumirn 3 normales.
    # Evitamos cooldown global moviendo el tiempo artificialmente entre extracciones
    t1 = NOW
    out1 = flow.process_queue(queue, t1)
    assert out1 is not None and out1.decision == EventDecision.SPOKEN

    t2 = t1 + timedelta(seconds=3.0)  # Ms que cooldown, pero sin tokens nuevos (8s)
    out2 = flow.process_queue(queue, t2)
    assert out2 is not None

    t3 = t2 + timedelta(seconds=3.0)
    out3 = flow.process_queue(queue, t3)
    assert out3 is not None

    # Se agotaron los tokens.
    t4 = t3 + timedelta(seconds=1.0)
    out4 = flow.process_queue(queue, t4)
    assert out4 is None  # No sale porque faltan tokens

    # Pero si llega un crtico, interrumpe aunque no haya tokens
    queue.push(ev_crit)
    out_crit = flow.process_queue(queue, t4 + timedelta(seconds=2.0))
    assert out_crit == ev_crit
