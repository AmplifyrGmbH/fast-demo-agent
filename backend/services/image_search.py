import asyncio
import base64
import json
import re
import aiohttp
from config import settings
from services import r2_client
from services.claude_client import call_claude, call_claude_multimodal, MODEL_HAIKU, MODEL_SONNET


# ─── Hilfsfunktionen ────────────────────────────────────────────────────────


def _haiku_query(context: str, orientation: str = "landscape") -> str:
    """Claude Haiku generiert einen englischen Unsplash-Suchbegriff."""
    orient_hint = "Querformat-Hintergrundbild" if orientation == "landscape" else "Bild (kein Portrait)"
    prompt = f"""Generiere einen präzisen englischen Suchbegriff (2-4 Wörter) für Unsplash,
der ein professionelles {orient_hint} findet. Fokus: Branche, Atmosphäre — KEIN Text, KEIN Logo.

{context}

Antworte NUR mit dem Suchbegriff, z.B.: "modern dental clinic interior"."""
    try:
        return call_claude(prompt, max_tokens=30, model=MODEL_HAIKU).strip().strip('"')
    except Exception:
        return "professional business"


async def _unsplash_download(query: str, orientation: str = "landscape") -> bytes | None:
    """Sucht auf Unsplash und gibt die Bild-Bytes zurück."""
    if not settings.UNSPLASH_ACCESS_KEY:
        return None
    try:
        params = {"query": query, "orientation": orientation, "content_filter": "high"}
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
                img_url = data["urls"]["regular"]

            async with session.get(img_url, timeout=aiohttp.ClientTimeout(total=20)) as img_resp:
                if img_resp.status != 200:
                    return None
                return await img_resp.read()
    except Exception:
        return None


async def _download_as_b64(url: str) -> tuple[str, str] | None:
    """Lädt ein Bild von URL und gibt (base64, media_type) zurück."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                ct = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
                if not ct.startswith("image/"):
                    return None
                data = await resp.read()
                if len(data) < 2000:
                    return None
                return base64.standard_b64encode(data).decode("utf-8"), ct
    except Exception:
        return None


# ─── Öffentliche Funktionen ──────────────────────────────────────────────────


def _build_context(plan: dict) -> str:
    firma = plan.get("firma", {})
    leistungen = []
    for s in plan.get("sektionen", []):
        if s.get("typ") == "leistungen":
            leistungen = [i.get("titel", "") for i in s.get("items", [])[:3]]
            break
    return (
        f"Firma: {firma.get('name', '')}\n"
        f"Beschreibung: {firma.get('beschreibung', '')}\n"
        f"Leistungen: {', '.join(leistungen)}"
    )


async def fetch_hero_image(plan: dict, build_id: int) -> str | None:
    """Unsplash-Hero: Querformat-Bild nach R2 hochladen, R2-URL zurückgeben."""
    context = _build_context(plan)
    query = _haiku_query(context, orientation="landscape")
    img_bytes = await _unsplash_download(query, orientation="landscape")
    if not img_bytes:
        return None
    r2_key = f"demos/{build_id}/hero_unsplash.jpg"
    return r2_client.upload_bytes(img_bytes, r2_key, "image/jpeg")


async def validate_and_replace_images(plan: dict, scraped_images: list, build_id: int) -> dict:
    """
    Prüft ob die Content-Bilder im Plan thematisch zum Unternehmen passen.
    Nicht passende oder fehlende Bilder werden durch Unsplash-Bilder ersetzt.

    Geprüft werden: ueber_uns.bild_url und alle nicht-hero/nicht-team Sektionen.
    Team-Portraits werden bewusst übersprungen (echte Personen).
    """
    if not settings.UNSPLASH_ACCESS_KEY:
        return plan

    # Content-Bilder aus Sektionen sammeln (kein Hero, kein Team)
    targets = []  # list of {"sektion": dict, "url": str, "typ": str}
    for s in plan.get("sektionen", []):
        if s.get("typ") in ("hero", "team"):
            continue
        if s.get("bild_url"):
            targets.append({"sektion": s, "url": s["bild_url"], "typ": s["typ"]})

    if not targets:
        return plan

    # Bilder herunterladen
    b64_results = await asyncio.gather(*[_download_as_b64(t["url"]) for t in targets])

    # Nur erfolgreich geladene weiterverarbeiten
    valid = [(t, b64) for t, b64 in zip(targets, b64_results) if b64]
    if not valid:
        return plan

    # Vision-Check mit Claude Sonnet
    firma = plan.get("firma", {})
    images_b64 = [b64 for _, b64 in valid]

    labels = "\n".join(
        f"Bild {i}: Sektion '{t['typ']}'" for i, (t, _) in enumerate(valid)
    )

    prompt = f"""Du bist ein Web-Design-Experte. Prüfe ob diese Bilder thematisch und atmosphärisch
zum Unternehmen passen. Antworte NUR mit JSON.

UNTERNEHMEN:
Name: {firma.get('name', '')}
Beschreibung: {firma.get('beschreibung', '')}

BILDER:
{labels}

Für jedes Bild entscheide: passt es zur Firma? Falls nicht, gib einen englischen Unsplash-Suchbegriff.

{{
  "checks": [
    {{"index": 0, "passend": true}},
    {{"index": 1, "passend": false, "unsplash_query": "modern clinic interior"}}
  ]
}}

Antworte NUR mit dem JSON-Objekt."""

    try:
        response = await asyncio.to_thread(
            call_claude_multimodal, prompt, images_b64, 512, MODEL_SONNET
        )
        match = re.search(r'\{[\s\S]*\}', response)
        if not match:
            return plan
        result = json.loads(match.group(0))
    except Exception:
        return plan

    # Nicht passende Bilder ersetzen
    for check in result.get("checks", []):
        if check.get("passend", True):
            continue
        idx = check.get("index")
        if idx is None or idx >= len(valid):
            continue

        target_sektion = valid[idx][0]["sektion"]
        query = check.get("unsplash_query") or _haiku_query(
            _build_context(plan), orientation="squarish"
        )

        img_bytes = await _unsplash_download(query, orientation="squarish")
        if not img_bytes:
            continue

        r2_key = f"demos/{build_id}/content_{idx}_unsplash.jpg"
        try:
            r2_url = r2_client.upload_bytes(img_bytes, r2_key, "image/jpeg")
            target_sektion["bild_url"] = r2_url
        except Exception:
            pass

    return plan
