import time
import anthropic
from config import settings

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

# Modell-Tier je nach Aufgabe
MODEL_OPUS = "claude-opus-4-6"      # Builder: Kernprodukt, maximale Qualität
MODEL_SONNET = "claude-sonnet-4-6"  # Analyst, Refinement: strukturiertes Reasoning
MODEL_HAIKU = "claude-haiku-4-5-20251001"  # Evaluator, Farberkennung: einfache Aufgaben


def call_claude(prompt: str, max_tokens: int = 8192, system: str = "",
                model: str = MODEL_SONNET, extended_output: bool = False) -> str:
    """
    Synchroner Wrapper um den Anthropic Client.
    Aus async-Funktionen immer via asyncio.to_thread() aufrufen.
    Gibt den Text-Content zurück. Max. 2 Retries bei Fehler.
    """
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    if extended_output:
        kwargs["extra_headers"] = {"anthropic-beta": "output-128k-2025-02-19"}

    last_error = None
    for attempt in range(3):
        try:
            response = client.messages.create(**kwargs)
            return response.content[0].text
        except Exception as e:
            last_error = e
            if attempt < 2:
                time.sleep(5)

    raise RuntimeError(f"Claude API Fehler nach 3 Versuchen: {last_error}")
