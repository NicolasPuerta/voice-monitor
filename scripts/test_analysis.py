"""Script de prueba para anlisis con Gemini sin usar recolectores reales."""

import logging
from pathlib import Path
import sys

# Agregar app al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.analysis import AnalysisAgent  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.gemini import GeminiClient  # noqa: E402
from app.domain.gemini import GeminiContext, SafeEventSummary  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    settings = Settings.load()
    if not settings.gemini.enabled or not settings.gemini.api_key:
        print("Error: Gemini no está habilitado o no hay API key configurada en .env.")
        print("Asegúrese de configurar GEMINI_ENABLED=true y GEMINI_API_KEY.")
        sys.exit(1)

    client = GeminiClient(settings)
    agent = AnalysisAgent(client)

    context = GeminiContext(
        system_load_avg=(6.5, 3.2, 1.1),
        memory_percent=92.5,
        primary_event=SafeEventSummary(
            event_type="cpu_spike",
            severity="critical",
            priority="critical",
            score=85.0,
            reasons=["Prioridad mxima por severidad o score excepcional."],
            app_key="ffmpeg",
            app_name="ffmpeg -i video.mp4",
            summary="Alto uso de CPU detectado (99%)",
            duration_s=45.0,
        ),
        process_knowledge=(
            "FFmpeg es una herramienta de conversin multimedia que "
            "tpicamente consume mucha CPU."
        ),
    )

    print("Enviando contexto de prueba a Gemini...")
    result = agent.analyze(context)

    if result:
        print("\n=== ANLISIS EXITOSO ===")
        print(f"Resumen:      {result.summary}")
        print(f"Confianza:    {result.confidence}")
        print(f"Explicacin:   {result.explanation}")
        print(f"Impacto:      {result.impact}")
        print(f"Riesgo:       {result.risk}")
        print(f"Texto Voz:    {result.speech_text}")
    else:
        print("\nEl anlisis fall o retorn un resultado invlido.")


if __name__ == "__main__":
    main()
