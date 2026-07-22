import asyncio
import base64
import json
import re
import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Build
from services.claude_client import call_claude, call_claude_multimodal, MODEL_SONNET


async def _images_as_b64(image_list: list) -> list[tuple[str, str]]:
    """Lädt hochgeladene R2-Bilder als base64 für Vision-Call."""
    urls = [img["r2"] for img in image_list if isinstance(img, dict) and img.get("r2")]
    if not urls:
        return []

    async def fetch(url: str) -> tuple[str, str] | None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return None
                    ct = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
                    data = await resp.read()
                    if len(data) < 500:
                        return None
                    return base64.standard_b64encode(data).decode("utf-8"), ct
        except Exception:
            return None

    results = await asyncio.gather(*[fetch(u) for u in urls[:5]])
    return [r for r in results if r]


def _build_prompt_analyst_prompt(user_prompt: str, num_images: int) -> str:
    bild_hinweis = (
        f"{num_images} Bild(er) beigefügt (Speisekarte, Fotos, Logo etc.) — nutze diese für den Plan."
        if num_images > 0 else "Keine Bilder hochgeladen."
    )

    return f"""Du bist ein erfahrener Web-Designer und Texter. Ein Kunde möchte eine neue Website
und hat sein Unternehmen beschrieben. Erstelle daraus einen detaillierten Bauplan.

BESCHREIBUNG DES UNTERNEHMENS:
{user_prompt}

HOCHGELADENE BILDER: {bild_hinweis}

AUFGABE:
Erstelle einen vollständigen Bauplan als JSON. Nutze die Beschreibung und Bilder.
Ergänze fehlende Infos sinnvoll mit KI — z.B. Leistungsbeschreibungen aus der Branche.

DESIGN-STILE (wähle passend zur Branche):
- modern-clean | modern-warm | bold-modern | professionell-klassisch
- minimalistisch | luxury | nature-organic | modern-tech

{{
  "firma": {{
    "name": "...",
    "tagline": "prägnanter Slogan — konkret, nicht generisch",
    "beschreibung": "2-3 Sätze",
    "adresse": "... oder null falls unbekannt",
    "telefon": "... oder null",
    "email": "... oder null"
  }},
  "logo_url": null,
  "design": {{
    "stil": "passender Stil",
    "primary_color": "#hex — passend zur Branche und Zielgruppe",
    "secondary_color": "#hex",
    "font_heading": "Google Font",
    "font_body": "Google Font",
    "button_style": "pill | rounded | sharp",
    "border_radius": "4px | 8px | 16px | 24px",
    "tone": "professionell | freundlich | seriös | modern | premium"
  }},
  "sektionen": [
    {{
      "typ": "hero",
      "headline": "starkes Nutzenversprechen — kein Firmenname",
      "subtext": "1-2 Sätze",
      "cta_text": "...",
      "cta_anchor": "#kontakt",
      "bild_url": null,
      "hintergrund": "gradient",
      "section_bg": "primary"
    }},
    {{
      "typ": "leistungen",
      "titel": "...",
      "layout": "sidebar-tabs",
      "section_bg": "light | white",
      "items": [
        {{"icon": "lucide-icon-name", "titel": "...", "beschreibung": "2-3 konkrete Sätze"}}
      ]
    }},
    {{
      "typ": "ueber_uns",
      "titel": "...",
      "layout": "image-left | image-right | centered-text",
      "section_bg": "white | light | primary",
      "text": "3-5 Sätze, persönlich und authentisch",
      "bild_url": null
    }},
    {{
      "typ": "kontakt",
      "titel": "...",
      "section_bg": "primary | dark | light",
      "adresse": "...",
      "telefon": "...",
      "email": "...",
      "oeffnungszeiten": []
    }}
  ],
  "ki_ergaenzungen": ["Was wurde durch KI ergänzt"]
}}

REGELN:
- Nur Sektionen einbauen für die genug Kontext da ist
- Fehlende Angaben (Adresse, Tel, etc.) als null setzen — nie erfinden
- Falls Bilder vorhanden: Inhalte aus Bildern (Speisekarte, Preise, etc.) in die Leistungen aufnehmen
- Leistungen icon: Lucide-Icon-Name passend zur Leistung.
  Verfügbare Icons: phone, mail, map-pin, clock, users, star, shield, heart,
  home, briefcase, settings, bar-chart, file-text, wrench, camera, zap, award,
  scissors, truck, coffee, utensils, stethoscope, graduation-cap, leaf, globe,
  credit-card, package, search, lock, sun, droplets, palette, music, book
- Antworte NUR mit dem JSON-Objekt"""


async def run_prompt_analyst(build_id: int, db: AsyncSession) -> dict:
    result = await db.execute(select(Build).where(Build.id == build_id))
    build = result.scalar_one()
    build.status = "analysing"
    build.status_detail = "Inhalte analysieren..."
    await db.commit()

    images_b64 = await _images_as_b64(build.scraped_images or [])
    prompt = _build_prompt_analyst_prompt(build.user_prompt or "", len(images_b64))

    if images_b64:
        response = await asyncio.to_thread(
            call_claude_multimodal, prompt, images_b64, 8192, MODEL_SONNET
        )
    else:
        response = await asyncio.to_thread(call_claude, prompt, 8192)

    match = re.search(r'\{[\s\S]*\}', response)
    plan = json.loads(match.group(0)) if match else json.loads(response)

    build.plan = plan
    build.status = "building"
    build.status_detail = None
    await db.commit()

    return plan
