import time
import anthropic
from config import settings

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
MODEL = "claude-sonnet-4-6"


def call_claude(prompt: str, max_tokens: int = 8192, system: str = "") -> str:
    """
    Synchroner Wrapper um den Anthropic Client.
    Aus async-Funktionen immer via asyncio.to_thread() aufrufen.
    Gibt den Text-Content zurück. Max. 2 Retries bei Fehler.
    """
    kwargs = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system

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
