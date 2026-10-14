"""Pruebas del AnalysisAgent con respuestas simuladas."""

import pytest
from unittest.mock import MagicMock

from app.core.analysis import AnalysisAgent
from app.domain.gemini import GeminiContext, SafeEventSummary


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock()
    return client


@pytest.fixture
def dummy_context() -> GeminiContext:
    return GeminiContext(
        system_load_avg=(2.5, 1.0, 0.5),
        memory_percent=85.0,
        primary_event=SafeEventSummary(
            event_type="cpu_spike",
            severity="high",
            priority="high",
            score=75.0,
            app_key="firefox",
            app_name="Firefox Web Browser",
            summary="High CPU usage detected",
            duration_s=15.0,
        ),
    )


def test_analysis_agent_parses_clean_json(
    mock_client: MagicMock, dummy_context: GeminiContext
) -> None:
    mock_client.generate.return_value = """
    {
      "summary": "Firefox consumiendo CPU.",
      "explanation": "El navegador web est usando muchos recursos.",
      "impact": "El sistema podra volverse ms lento.",
      "confidence": "alta",
      "risk": "Bajo",
      "speech_text": "Firefox est consumiendo mucha CPU, quizs debas revisar tus pestaas."
    }
    """

    agent = AnalysisAgent(mock_client)
    res = agent.analyze(dummy_context)

    assert res is not None
    assert res.summary == "Firefox consumiendo CPU."
    assert res.confidence == "alta"
    assert "revisar tus pestaas" in res.speech_text


def test_analysis_agent_parses_markdown_json(
    mock_client: MagicMock, dummy_context: GeminiContext
) -> None:
    mock_client.generate.return_value = """
    ```json
    {
      "summary": "Resumen",
      "explanation": "Explicacin",
      "impact": "Impacto",
      "confidence": "media",
      "risk": "Riesgo",
      "speech_text": "Texto"
    }
    ```
    """

    agent = AnalysisAgent(mock_client)
    res = agent.analyze(dummy_context)

    assert res is not None
    assert res.summary == "Resumen"


def test_analysis_agent_returns_none_on_invalid_json(
    mock_client: MagicMock, dummy_context: GeminiContext
) -> None:
    mock_client.generate.return_value = "Lo siento, no puedo analizar esto."

    agent = AnalysisAgent(mock_client)
    res = agent.analyze(dummy_context)

    assert res is None


def test_analysis_agent_returns_none_on_validation_error(
    mock_client: MagicMock, dummy_context: GeminiContext
) -> None:
    # Faltan campos requeridos en el JSON
    mock_client.generate.return_value = """{"summary": "Hola"}"""

    agent = AnalysisAgent(mock_client)
    res = agent.analyze(dummy_context)

    assert res is None
