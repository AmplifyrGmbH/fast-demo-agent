import asyncio
import json
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Build
from services.claude_client import call_claude, MODEL_OPUS


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
- Vollständiges, valides HTML5 mit <!DOCTYPE html>
- Gesamter CSS im <style>-Tag (kein externes Stylesheet)
- Google Fonts via <link> einbinden (die im Bauplan definierten Fonts)
- Vollständig responsive: Mobile-first, Breakpoints bei 768px und 1200px
- Smooth-scroll Navigation mit Anchor-Links
- Mobile Hamburger-Menu (reines CSS oder minimales JS)
- Kein jQuery, kein CSS-Framework (kein Bootstrap/Tailwind)
- Keine externen Abhängigkeiten ausser Google Fonts

DESIGN-ANFORDERUNGEN:
- Modernes, professionelles Design — viel Weissraum, klare Typographie
- Die Primärfarbe aus dem Bauplan konsequent einsetzen (Buttons, Akzente, Header)
- Bilder als <img src="r2_url"> einbinden mit object-fit: cover
- Hover-Effekte auf Buttons und interaktiven Elementen
- Smooth Scrolling: html {{ scroll-behavior: smooth; }}
- Jede Sektion bekommt eine id (z.B. id="leistungen") für Anchor-Navigation

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
    response = await asyncio.to_thread(call_claude, prompt, 8192, "", MODEL_OPUS)
    html = extract_html(response)

    return html
