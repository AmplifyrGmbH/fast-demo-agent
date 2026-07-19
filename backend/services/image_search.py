import aiohttp
from config import settings
from services import r2_client
from services.claude_client import call_claude, MODEL_HAIKU


def _build_search_query(plan: dict) -> str:
    """Leitet einen englischen Unsplash-Suchbegriff aus dem Bauplan ab."""
    firma = plan.get("firma", {})
    beschreibung = firma.get("beschreibung", "")
    name = firma.get("name", "")
    leistungen = plan.get("sektionen", [])
    services_text = ""
    for s in leistungen:
        if s.get("typ") == "leistungen":
            items = s.get("items", [])
            services_text = " ".join(i.get("titel", "") for i in items[:3])
            break

    context = f"Firma: {name}\nBeschreibung: {beschreibung}\nLeistungen: {services_text}"

    prompt = f"""Generiere einen präzisen englischen Suchbegriff (2-4 Wörter) für Unsplash,
der ein professionelles Querformat-Hintergrundbild für diese Website findet.
Fokus: Branche, Atmosphäre, professionell — KEIN Text, KEIN Logo.

{context}

Antworte NUR mit dem Suchbegriff, z.B.: "modern dental clinic interior" oder "cozy restaurant dining"."""

    try:
        return call_claude(prompt, max_tokens=30, model=MODEL_HAIKU).strip().strip('"')
    except Exception:
        return f"{name} professional business"


async def fetch_hero_image(plan: dict, build_id: int) -> str | None:
    """
    Sucht auf Unsplash ein passendes Querformat-Bild, lädt es herunter und
    lädt es nach R2 hoch. Gibt die R2-URL zurück oder None bei Fehler.
    """
    if not settings.UNSPLASH_ACCESS_KEY:
        return None

    query = _build_search_query(plan)

    try:
        params = {
            "query": query,
            "orientation": "landscape",
            "content_filter": "high",
        }
        headers = {"Authorization": f"Client-ID {settings.UNSPLASH_ACCESS_KEY}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.unsplash.com/photos/random",
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                img_url = data["urls"]["regular"]  # 1080px Breite

            # Bild herunterladen
            async with session.get(img_url, timeout=aiohttp.ClientTimeout(total=20)) as img_resp:
                if img_resp.status != 200:
                    return None
                img_bytes = await img_resp.read()

        # Nach R2 hochladen
        r2_key = f"demos/{build_id}/hero_unsplash.jpg"
        r2_url = r2_client.upload_bytes(img_bytes, r2_key, "image/jpeg")
        return r2_url

    except Exception:
        return None
