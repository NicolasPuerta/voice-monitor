"""Pruebas del cliente Gemini asegurando aislamiento y lmites."""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.core.config import AppSettings, GeminiSettings, Settings
from app.core.privacy import PrivacySanitizer
from app.core.gemini import (
    CircuitBreaker,
    GeminiClient,
    GeminiContextBuilder,
    CircuitState,
)
from app.domain.gemini import GeminiContext, SafeEventSummary
from app.domain.events import Event, EventMetadata, ScoreResult, ScoreBreakdown
from app.domain.enums import EventType, EventSeverity, EventPriority
from app.domain.context import SystemContext
from app.domain.snapshots import ResourceSnapshot
from google.api_core.exceptions import ResourceExhausted

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def sanitizer() -> PrivacySanitizer:
    return PrivacySanitizer("/home/user")


@pytest.fixture
def mock_settings() -> Settings:
    settings = Settings(
        app=AppSettings(),
        gemini=GeminiSettings(
            enabled=True, model="gemini-2.5-flash", api_key="TEST_API_KEY"
        ),
    )
    return settings


def test_gemini_context_builder_strips_secrets(sanitizer: PrivacySanitizer) -> None:
    builder = GeminiContextBuilder(sanitizer)

    event = Event(
        event_type=EventType.CPU_SPIKE,
        severity=EventSeverity.CRITICAL,
        summary="Spike in https://admin:pass@host",
        metadata=EventMetadata(
            app_key="cmd:python script.py", app_name="python /home/user/script.py"
        ),
    )
    event.score_result = ScoreResult(
        score=99.0,
        priority=EventPriority.CRITICAL,
        breakdown=ScoreBreakdown(
            impact=1, novelty=1, anomaly=1, risk=1, relevance=1, repetition_penalty=1
        ),
    )

    sys_ctx = SystemContext(
        collected_at=NOW,
        resources=ResourceSnapshot(
            cpu_percent=50.0,
            cpu_count_logical=4,
            memory_total_bytes=1000,
            memory_used_bytes=500,
            memory_available_bytes=500,
            memory_percent=50.0,
        ),
    )

    ctx = builder.build(event, sys_ctx, "Known process AKIAIOSFODNN7EXAMPLE")

    # Validar sanitizacin
    assert "admin:pass" not in ctx.primary_event.summary
    assert "***:***" in ctx.primary_event.summary

    assert "/home/user" not in ctx.primary_event.app_name
    assert "~" in ctx.primary_event.app_name

    assert "AKIAIOSFODNN7EXAMPLE" not in ctx.process_knowledge
    assert "***AWS_KEY***" in ctx.process_knowledge


@patch("app.core.gemini.genai")
def test_gemini_client_respects_circuit_breaker(
    mock_genai: MagicMock, mock_settings: Settings
) -> None:
    breaker = CircuitBreaker(failure_threshold=1)  # 1 fallo y abre
    client = GeminiClient(mock_settings, circuit_breaker=breaker)

    ctx = GeminiContext(
        system_load_avg=(0, 0, 0),
        memory_percent=10,
        primary_event=SafeEventSummary(
            event_type="cpu",
            severity="high",
            priority="high",
            score=50,
            app_key="app",
            app_name="app",
            summary="sum",
        ),
    )

    # 1. Configuramos el mock para lanzar ResourceExhausted (rate limit 429)
    client.model.generate_content.side_effect = ResourceExhausted("Rate limit")

    # Deshabilitamos el sleep de backoff para que el test no espere
    with patch("app.core.gemini.time.sleep"):
        res = client.generate(ctx.model_dump_json())

    assert res is None
    assert breaker.state == CircuitState.OPEN

    # 2. Siguiente llamada debera ser denegada inmediatamente sin llamar al SDK
    client.model.generate_content.reset_mock()
    res2 = client.generate(ctx.model_dump_json())
    assert res2 is None
    client.model.generate_content.assert_not_called()


@patch("app.core.gemini.genai")
def test_gemini_client_disabled(mock_genai: MagicMock) -> None:
    settings = Settings(gemini=GeminiSettings(enabled=False))
    client = GeminiClient(settings)

    assert client.model is None

    res = client.generate("test")
    assert res is None
    mock_genai.GenerativeModel.assert_not_called()
