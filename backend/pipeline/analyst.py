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

    logo_url = build.logo_url or ""
    screenshot_url = build.screenshot_url or ""

    return f"""Du bist ein erfahrener Web-Designer und Texter. Du bekommst alle verfügbaren Daten
einer Unternehmens-Website und sollst daraus einen Bauplan für eine neue, moderne,
professionelle Website erstellen.

VERFÜGBARE DATEN:
=== WEBSITE TEXT ===
{build.scraped_text or ""}

=== INHALTSBILDER (R2-URLs, bereits gespiegelt) ===
{images_json}

=== SCREENSHOT DER BESTEHENDEN WEBSITE (nur zur Referenz — NICHT als Hero-Bild verwenden) ===
{screenshot_url}

=== LOGO (diese exakte URL verwenden falls vorhanden) ===
{logo_url or "kein Logo gefunden"}

=== PRIMÄRFARBE DER ALTEN WEBSITE ===
{build.primary_color or "#2563eb"}

{user_prompt_section}

AUFGABE:
Erstelle einen detaillierten Bauplan als JSON. Triff bewusste Design-Entscheidungen — nicht generisch,
sondern passend zur Branche und Zielgruppe.

DESIGN-STILE (wähle den passendsten):
- modern-clean: Klare Linien, viel Weissraum, subtile Schatten, Pill-Buttons
- modern-warm: Runde Ecken (16px+), warme Töne, einladend, freundlich
- bold-modern: Grosse Typographie, starke Kontraste, dunkle Sektionen, mutige Akzente
- professionell-klassisch: Serif-Fonts, strukturiert, konservativ, vertrauenswürdig
- minimalistisch: Maximales Weissraum, dünne Linien, reduziert, elegant
- luxury: Premium-Anmutung, Gold/Dunkel-Töne, Serif, viel Spacing
- nature-organic: Organisch, Erdtöne, runde Formen, nachhaltig-frisch
- modern-tech: Gradients, präzise Grid, technisch-clean, innovativ

SECTION-LAYOUTS (je nach Inhalt wählen):
- leistungen layout: "cards-3" | "cards-4" | "icon-list" | "two-column-icons"
- ueber_uns layout: "image-left" | "image-right" | "centered-text"
- team layout: "cards-3" | "cards-4" | "list"

SECTION-HINTERGRÜNDE (für visuelle Abwechslung — nie zweimal dasselbe hintereinander):
"white" | "light" | "primary" | "dark"

{{
  "firma": {{
    "name": "...",
    "tagline": "prägnanter Slogan — nicht generisch, sondern spezifisch für diese Firma",
    "beschreibung": "2-3 Sätze über die Firma",
    "adresse": "...",
    "telefon": "...",
    "email": "..."
  }},
  "logo_url": "exakte R2-URL des Logos oder null",
  "design": {{
    "stil": "einer der 8 Stile oben — passend zur Branche",
    "primary_color": "#hex — beibehalten oder verbessern wenn veraltet",
    "secondary_color": "#hex — harmonisch zur Primary, nicht zu ähnlich",
    "font_heading": "Google Font — passend zum Stil (z.B. Playfair Display, Montserrat, Space Grotesk, Syne, DM Serif Display)",
    "font_body": "Google Font — gut lesbar (z.B. Inter, Lato, Source Sans 3, DM Sans)",
    "button_style": "pill | rounded | sharp",
    "border_radius": "4px | 8px | 16px | 24px",
    "tone": "professionell | freundlich | seriös | modern | premium | vertrauenswürdig"
  }},
  "sektionen": [
    {{
      "typ": "hero",
      "headline": "starke, spezifische Headline — kein Firmenname, sondern Nutzenversprechen",
      "subtext": "1-2 Sätze die das Angebot konkret beschreiben",
      "cta_text": "...",
      "cta_anchor": "#kontakt",
      "bild_url": "r2-url oder null",
      "hintergrund": "bild | gradient | dark",
      "section_bg": "primary"
    }},
    {{
      "typ": "leistungen",
      "titel": "...",
      "layout": "cards-3 | cards-4 | icon-list | two-column-icons",
      "section_bg": "light | white | dark",
      "items": [
        {{"icon": "emoji", "titel": "...", "beschreibung": "konkrete Beschreibung, mind. 1 Satz"}}
      ]
    }},
    {{
      "typ": "ueber_uns",
      "titel": "...",
      "layout": "image-left | image-right | centered-text",
      "section_bg": "white | light | primary",
      "text": "persönlich und authentisch, 3-5 Sätze",
      "bild_url": "r2-url oder null"
    }},
    {{
      "typ": "team",
      "titel": "...",
      "layout": "cards-3 | cards-4 | list",
      "section_bg": "light | white",
      "mitglieder": [
        {{"name": "...", "rolle": "...", "bild_url": "r2-url oder null"}}
      ]
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
  "ki_ergaenzungen": ["Liste was KI selbst ergänzt hat"]
}}

REGELN:
- Nur Sektionen einbauen für die genug Content vorhanden ist
- Fehlende Inhalte SELBST sinnvoll ergänzen — nie Platzhalter
- logo_url: exakt die Logo-URL übernehmen (nicht verändern), oder null
- Hero: Querformat-Bilder bevorzugen. Kein passendes Bild vorhanden → hintergrund="gradient", bild_url=null. Der Screenshot darf NIEMALS als Hero-Bild verwendet werden.
- section_bg variieren — nie weiss-weiss oder gleiche Farbe zweimal hintereinander
- Bilder: Jedes Bild nur einmal verwenden
- Tagline und Headline: konkret und einprägsam, nicht generisch
- Antworte NUR mit dem JSON-Objekt, kein anderer Text"""


async def run_analyst(build_id: int, db: AsyncSession) -> dict:
    result = await db.execute(select(Build).where(Build.id == build_id))
    build = result.scalar_one()
    build.status_detail = "Inhalte analysieren..."
    await db.commit()

    prompt = build_analyst_prompt(build)
    response = await asyncio.to_thread(call_claude, prompt, 8192)

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
