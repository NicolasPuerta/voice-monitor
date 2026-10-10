"""Agente de anlisis que utiliza Gemini para interpretar contextos."""

import json
import logging
from app.core.gemini import GeminiClient
from app.domain.gemini import GeminiContext, AnalysisResult
from app.domain.prompts import ANALYSIS_SYSTEM_PROMPT_V1

logger = logging.getLogger(__name__)


class AnalysisAgent:
    """Interpreta eventos del sistema y genera explicaciones narrativas usando Gemini."""

    def __init__(self, client: GeminiClient):
        self.client = client
        self.system_prompt = ANALYSIS_SYSTEM_PROMPT_V1

    def analyze(self, context: GeminiContext) -> AnalysisResult | None:
        """Enva el contexto a Gemini y parsea la respuesta JSON."""
        prompt = context.model_dump_json(indent=2)

        raw_response = self.client.generate(
            prompt=prompt, system_instruction=self.system_prompt
        )

        if not raw_response:
            return None

        return self._parse_response(raw_response)

    def _parse_response(self, text: str) -> AnalysisResult | None:
        """Extrae el JSON de la respuesta de Gemini y valida el modelo."""
        # Limpiar posible bloque de cdigo Markdown (```json ... ```)
        clean_text = text.strip()
        if clean_text.startswith("```"):
            lines = clean_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_text = "\n".join(lines).strip()

        try:
            data = json.loads(clean_text)
            return AnalysisResult.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Error parseando respuesta de Gemini: {e}\nTexto crudo: {text}")
            return None
