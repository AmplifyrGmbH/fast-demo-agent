import asyncio
import json
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Build
from services.claude_client import call_claude, MODEL_OPUS, MODEL_SONNET


def extract_html(response: str) -> str:
    match = re.search(r"```html\s*(.*?)```", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    if response.strip().startswith("<!DOCTYPE") or response.strip().startswith("<html"):
        return response.strip()
    return response.strip()


def build_builder_prompt(build: Build, fix_instructions: str = "") -> str:
    plan_json = json.dumps(build.plan or {}, ensure_ascii=False, indent=2)

    fix_section = ""
    if fix_instructions:
        fix_section = f"""
KORREKTUREN (vom Evaluator gemeldet — bitte beheben):
{fix_instructions}
"""

    return f"""Du bist ein Experte für moderne, professionelle Websites. Generiere eine vollständige,
individuelle Onepager-Website als einzelne HTML-Datei.

BAUPLAN:
{plan_json}

{fix_section}

TECHNISCHE ANFORDERUNGEN:
- Vollständiges, valides HTML5 mit <!DOCTYPE html> — die Datei MUSS mit </html> enden
- Gesamter CSS im <style>-Tag (kein externes Stylesheet)
- CSS KOMPAKT halten: max. 250 Zeilen, nur das Notwendige — kein Over-Engineering
- Google Fonts via <link> einbinden (die im Bauplan definierten Fonts)
- Vollständig responsive: Mobile-first, ein Breakpoint bei 768px genügt
- Mobile Hamburger-Menu (minimales JS, max. 20 Zeilen)
- Kein jQuery, kein CSS-Framework (kein Bootstrap/Tailwind)
- Keine externen Abhängigkeiten ausser Google Fonts

DESIGN-ANFORDERUNGEN:
- Modernes, professionelles Design — viel Weissraum, klare Typographie
- Die Primärfarbe aus dem Bauplan konsequent einsetzen (Buttons, Akzente, Header)
- Bilder als <img src="r2_url"> einbinden mit object-fit: cover
- Hover-Effekte nur auf Buttons und CTAs — keine komplexen Animationen
- Smooth Scrolling: html {{ scroll-behavior: smooth; }}
- Jede Sektion bekommt eine id für Anchor-Navigation — PFLICHT: id="leistungen", id="ueber-uns", id="team", id="kontakt"

CONTENT-ANFORDERUNGEN:
- ALLE Inhalte aus dem Bauplan verwenden — kein Platzhalter, kein "Lorem ipsum"
- Echte Texte, echte Namen, echte Telefonnummern
- Bewertungen authentisch darstellen (Sterne als ★-Zeichen)
- Falls Logo vorhanden: im Header einbinden

STRUKTUR:
1. <head>: Charset UTF-8, Viewport, Title, Google Fonts Link, <style>
2. <header>: Logo + Firmenname, Navigation mit Anchor-Links, Hamburger-Menu Mobile
3. <main>: Sektionen in der Reihenfolge aus dem Bauplan
4. <footer>: Firmenname, Adresse, Telefon, Copyright

Gib NUR die vollständige HTML-Datei aus, kein anderer Text, kein Markdown-Codeblock."""


async def run_builder(build_id: int, db: AsyncSession, fix_instructions: str = "") -> str:
    result = await db.execute(select(Build).where(Build.id == build_id))
    build = result.scalar_one()

    if not fix_instructions:
        build.status_detail = "HTML generieren..."
    else:
        build.status_detail = f"Korrekturen einarbeiten (Runde {build.evaluator_rounds})..."
    await db.commit()

    prompt = build_builder_prompt(build, fix_instructions)
    response = await asyncio.to_thread(call_claude, prompt, 16000, "", MODEL_OPUS, True)
    html = extract_html(response)

    return html
