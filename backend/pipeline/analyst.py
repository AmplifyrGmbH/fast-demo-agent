import asyncio
import json
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Build
from services.claude_client import call_claude


def build_analyst_prompt(build: Build) -> str:
    images_json = json.dumps(build.scraped_images or [], ensure_ascii=False, indent=2)

    user_prompt_section = ""
    if build.user_prompt:
        user_prompt_section = f"""
=== SPEZIFISCHE WÜNSCHE DES AUFTRAGGEBERS (haben höchste Priorität) ===
{build.user_prompt}
"""

    return f"""Du bist ein erfahrener Web-Designer und Texter. Du bekommst alle verfügbaren Daten
einer Unternehmens-Website und sollst daraus einen Bauplan für eine neue, moderne,
professionelle Website erstellen.

VERFÜGBARE DATEN:
=== WEBSITE TEXT ===
{build.scraped_text or ""}

=== BILDER (R2-URLs, bereits gespiegelt) ===
{images_json}

=== LOGO ===
{build.logo_url or "kein Logo gefunden"}

=== PRIMÄRFARBE DER ALTEN WEBSITE ===
{build.primary_color or "#2563eb"}

{user_prompt_section}

AUFGABE:
Erstelle einen detaillierten Bauplan als JSON mit folgender Struktur:

{{
  "firma": {{
    "name": "Zahnarztpraxis Muster",
    "tagline": "kurzer Slogan (aus Website oder selbst formuliert)",
    "beschreibung": "2-3 Sätze über die Firma",
    "adresse": "...",
    "telefon": "...",
    "email": "..."
  }},
  "design": {{
    "stil": "modern-warm | modern-clean | professionell-klassisch | minimalistisch",
    "primary_color": "#hex",
    "secondary_color": "#hex",
    "font_heading": "Google Font Name",
    "font_body": "Google Font Name",
    "tone": "professionell | freundlich | seriös | modern"
  }},
  "sektionen": [
    {{
      "typ": "hero",
      "headline": "...",
      "subtext": "...",
      "cta_text": "...",
      "cta_anchor": "#kontakt",
      "bild_url": "r2-url oder null",
      "hintergrund": "bild | farbe | gradient"
    }},
    {{
      "typ": "leistungen",
      "titel": "...",
      "items": [
        {{"icon": "emoji", "titel": "...", "beschreibung": "..."}}
      ]
    }},
    {{
      "typ": "ueber_uns",
      "titel": "...",
      "text": "...",
      "bild_url": "r2-url oder null"
    }},
    {{
      "typ": "team",
      "titel": "...",
      "mitglieder": [
        {{"name": "...", "rolle": "...", "bild_url": "r2-url oder null"}}
      ]
    }},
    {{
      "typ": "kontakt",
      "titel": "...",
      "adresse": "...",
      "telefon": "...",
      "email": "...",
      "oeffnungszeiten": []
    }}
  ],
  "ki_ergaenzungen": ["Liste was KI selbst ergänzt hat"]
}}

REGELN:
- Nur Sektionen einbauen für die genug Content vorhanden ist
- Fehlende Inhalte (z.B. Leistungsbeschreibungen) SELBST sinnvoll ergänzen
- Bilder: Jedes Bild nur einmal verwenden, bestes Bild ins Hero
- Primärfarbe beibehalten wenn zeitgemäss, sonst verbessern
- Antworte NUR mit dem JSON-Objekt, kein anderer Text"""


async def run_analyst(build_id: int, db: AsyncSession) -> dict:
    result = await db.execute(select(Build).where(Build.id == build_id))
    build = result.scalar_one()
    build.status_detail = "Inhalte analysieren..."
    await db.commit()

    prompt = build_analyst_prompt(build)
    response = await asyncio.to_thread(call_claude, prompt, 4096)

    # JSON aus Response extrahieren
    match = re.search(r'\{[\s\S]*\}', response)
    if match:
        plan = json.loads(match.group(0))
    else:
        plan = json.loads(response)

    build.plan = plan
    build.status = "building"
    build.status_detail = None
    await db.commit()

    return plan
