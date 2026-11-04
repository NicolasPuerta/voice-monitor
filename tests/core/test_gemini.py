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
from app.domain.snapshots import PressureStall, ResourceSnapshot, SystemPressure
from google.genai import errors

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


def test_gemini_context_builder_includes_cpu_and_psi(
    sanitizer: PrivacySanitizer,
) -> None:
    builder = GeminiContextBuilder(sanitizer)
    event = Event(
        event_type=EventType.CPU_SPIKE,
        severity=EventSeverity.HIGH,
        summary="CPU alta",
        detected_at=NOW,
    )
    sys_ctx = SystemContext(
        collected_at=NOW,
        resources=ResourceSnapshot(
            cpu_percent=87.5,
            cpu_count_logical=8,
            load_average=(6.0, 4.0, 2.0),
            memory_total_bytes=16_000,
            memory_used_bytes=4_000,
            memory_available_bytes=12_000,
            memory_percent=25.0,
        ),
        pressure=SystemPressure(
            cpu_some=PressureStall(avg10=31.5, avg60=10.0, avg300=2.0),
            io_some=PressureStall(avg10=4.0, avg60=1.0, avg300=0.5),
        ),
    )

    ctx = builder.build(event, sys_ctx)

    assert ctx.cpu_percent == 87.5
    assert ctx.cpu_count_logical == 8
    assert ctx.system_load_avg == (6.0, 4.0, 2.0)
    assert ctx.cpu_pressure_avg10 == 31.5
    assert ctx.memory_pressure_avg10 is None
    assert ctx.io_pressure_avg10 == 4.0


def _ctx() -> GeminiContext:
    return GeminiContext(
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


def _api_error(code: int) -> errors.APIError:
    return errors.APIError(code, {"error": {"message": f"HTTP {code}"}})


@patch("app.core.gemini.genai")
def test_gemini_client_respects_circuit_breaker(
    mock_genai: MagicMock, mock_settings: Settings
) -> None:
    breaker = CircuitBreaker(failure_threshold=1)  # 1 fallo y abre
    client = GeminiClient(mock_settings, circuit_breaker=breaker)
    generate = client.client.models.generate_content  # type: ignore[union-attr]

    # 1. Rate limit (429): abre el circuito
    generate.side_effect = _api_error(429)
    with patch("app.core.gemini.time.sleep"):
        res = client.generate(_ctx().model_dump_json())

    assert res is None
    assert breaker.state == CircuitState.OPEN

    # 2. Siguiente llamada denegada inmediatamente sin llamar al SDK
    generate.reset_mock()
    res2 = client.generate(_ctx().model_dump_json())
    assert res2 is None
    generate.assert_not_called()


@patch("app.core.gemini.genai")
def test_gemini_client_retries_transient_errors(
    mock_genai: MagicMock, mock_settings: Settings
) -> None:
    client = GeminiClient(mock_settings, circuit_breaker=CircuitBreaker(5))
    generate = client.client.models.generate_content  # type: ignore[union-attr]
    generate.side_effect = [_api_error(503), MagicMock(text='{"ok": true}')]

    with patch("app.core.gemini.time.sleep") as sleep:
        assert client.generate("prompt", system_instruction="sys") == '{"ok": true}'

    assert generate.call_count == 2
    sleep.assert_called_once_with(1)
    config = generate.call_args.kwargs["config"]
    assert config.system_instruction == "sys"
    assert config.response_mime_type == "application/json"
    assert generate.call_args.kwargs["model"] == mock_settings.gemini.model


@patch("app.core.gemini.genai")
def test_gemini_client_does_not_retry_invalid_key(
    mock_genai: MagicMock, mock_settings: Settings
) -> None:
    client = GeminiClient(mock_settings, circuit_breaker=CircuitBreaker(5))
    generate = client.client.models.generate_content  # type: ignore[union-attr]
    generate.side_effect = _api_error(400)

    with patch("app.core.gemini.time.sleep") as sleep:
        assert client.generate("prompt") is None

    assert generate.call_count == 1
    sleep.assert_not_called()


@patch("app.core.gemini.genai")
def test_gemini_client_disables_thinking_only_on_2_5_flash(
    mock_genai: MagicMock,
) -> None:
    def client_for(model: str) -> GeminiClient:
        return GeminiClient(
            Settings(gemini=GeminiSettings(enabled=True, api_key="k", model=model))
        )

    flash = client_for("gemini-2.5-flash")
    pro = client_for("gemini-2.5-pro")
    newer = client_for("gemini-3.5-flash-lite")
    flash_cfg = flash._build_config(None)  # pylint: disable=protected-access
    pro_cfg = pro._build_config(None)  # pylint: disable=protected-access
    assert flash_cfg.thinking_config is not None
    assert flash_cfg.thinking_config.thinking_budget == 0
    assert pro_cfg.thinking_config is None
    newer_cfg = newer._build_config(None)  # pylint: disable=protected-access
    assert newer_cfg.thinking_config is None


@patch("app.core.gemini.genai")
def test_gemini_client_disabled(mock_genai: MagicMock) -> None:
    settings = Settings(gemini=GeminiSettings(enabled=False))
    client = GeminiClient(settings)

    assert client.client is None

    res = client.generate("test")
    assert res is None
    mock_genai.Client.assert_not_called()
