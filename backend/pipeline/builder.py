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

    return f"""Du bist ein Senior Web Designer und Frontend-Entwickler. Erstelle eine visuell
beeindruckende, individuelle Onepager-Website als einzelne HTML-Datei.
Zeige echte Designqualität — nicht generisch, sondern charakterstark.

BAUPLAN:
{plan_json}

{fix_section}

━━━ TECHNISCHE ANFORDERUNGEN ━━━
- Vollständiges, valides HTML5 mit <!DOCTYPE html> — die Datei MUSS mit </html> enden
- Gesamter CSS im <style>-Tag (kein externes Stylesheet), bis 500 Zeilen erlaubt
- Google Fonts via <link> (die im Bauplan definierten Fonts)
- Responsive: Mobile-first, Breakpoints bei 768px und 1024px
- Hamburger-Menu Mobile (vanilla JS, max. 25 Zeilen)
- Fade-in beim Scrollen via IntersectionObserver (max. 20 Zeilen JS, class="fade-in")
- Kein jQuery, kein CSS-Framework

━━━ DESIGN-SYSTEM (nach plan.design.stil) ━━━

modern-clean:
  Sektionen: weiss/#f8fafc alternierend | Cards: box-shadow:0 2px 16px rgba(0,0,0,.07)
  Buttons: border-radius:50px (pill) | H1: 3.5rem, font-weight:800
  Leistungen: 3-er Grid mit Icon oben, Titel, Text

modern-warm:
  Cards/Elemente: border-radius:20px | Schatten warm: box-shadow:0 8px 32px rgba(0,0,0,.10)
  Buttons: border-radius:14px | H1: 3rem, font-weight:700
  Hintergründe: weich, cremig (#fefcf9 als light), warme Akzentflächen

bold-modern:
  Hero: dunkel (background:#0f0f0f oder sehr dunkle Primary) mit heller Schrift
  H1: 4.5rem+, letter-spacing:-2px, font-weight:900 | Diagonale Trenner: clip-path:polygon(0 0,100% 0,100% 90%,0 100%)
  Maximaler Kontrast, mutige Farbflächen, minimalistische Struktur

professionell-klassisch:
  Serif-Headings, gedeckte Töne | Trennlinien statt Cards | Viel Zeilenabstand (line-height:1.8)
  Dezente Hover-Effekte | Strukturiertes 2-Spalten-Layout für Inhalte

minimalistisch:
  Extremes Weissraum (section padding: 120px 0) | Keine Shadows, keine Borders
  H1: gross und dünn (font-weight:300, 4rem) | Farbe nur als Akzentpunkt einsetzen

luxury:
  Dunkel-Gold Palette | Serif-Headings (Playfair Display) | Grosszügige Proportionen
  Goldene Akzentlinie: border-top:2px solid gold | Animierte Unterstreichungen bei Links

nature-organic:
  Erdtöne, weiche Formen | border-radius:24px+ | Organische SVG-Divider zwischen Sektionen
  Grün-Akzente, natürliche Bildkomposition | Lockerere Typographie

modern-tech:
  Gradient-Akzente auf Buttons und Headings | Präzises Grid-Layout
  Code-Anmutung bei Badges | Klare, technische Struktur | Blaue/violette Töne

━━━ SECTION-LAYOUTS (plan.sektionen[].layout verwenden) ━━━
cards-3: CSS Grid, 3 Spalten, gleiche Karten
cards-4: CSS Grid, 4 Spalten (bei Mobile 2 Spalten)
icon-list: Zweispaltig, Icon links + Text rechts, grosszügig
two-column-icons: Zwei Gruppen à 2-3 Icons nebeneinander
image-left / image-right: 50/50 Split, Bild und Text
centered-text: Zentrierter Textblock, max 700px Breite

━━━ SECTION-HINTERGRÜNDE (plan.sektionen[].section_bg verwenden) ━━━
white: #ffffff
light: #f8fafc (oder stilpassend: #fef9f5 bei warm, etc.)
primary: Primärfarbe aus plan — helle Schrift
dark: #0f172a oder ähnlich — weisse Schrift

━━━ CONTENT-ANFORDERUNGEN ━━━
- ALLE Inhalte aus dem Bauplan — kein Platzhalter, kein Lorem ipsum
- Echte Texte, Namen, Telefonnummern, Adressen
- LOGO: plan.logo_url vorhanden → <img src="logo_url"> im Header. Kein Emoji-Ersatz.
- HERO hintergrund="gradient" → CSS-Gradient aus Primary. "dark" → #0f172a + helle Schrift. "bild" → <img> mit overlay (rgba(0,0,0,.45)).
- HERO-SEKTION enthält NUR: Hintergrundbild/Gradient, Headline, Subtext, CTA-Button. KEINE anderen Inhalte (keine Öffnungszeiten, keine Kontaktdaten, keine Leistungslisten, kein Logo gross im Hero).
- Leistungs-Emojis gross und als echte visuelle Akzente einsetzen (font-size:2.5rem)

━━━ ANIMATIONEN ━━━
- Smooth Scroll: html {{ scroll-behavior: smooth; }}
- Fade-in: .fade-in {{ opacity:0; transform:translateY(24px); transition:opacity .6s,transform .6s; }}
         .fade-in.visible {{ opacity:1; transform:none; }}
  IntersectionObserver beobachtet alle .fade-in Elemente (threshold:0.15)
- Hover auf Cards: transform:translateY(-4px), Schatten verstärken
- Hover auf Buttons: leichte Aufhellung + leichter Schatten
- Header: beim Scrollen leicht verkleinern (scrolled-Klasse via JS) — subtil

━━━ STRUKTUR ━━━
1. <head>: Charset, Viewport, Title, Google Fonts Link, <style>
2. <header>: Logo + Firmenname, Nav mit Anchor-Links, Hamburger Mobile — scrollt mit (sticky)
3. <main>: Sektionen aus Bauplan, jede mit class="fade-in"
4. <footer>: Firmenname, Adresse, Telefon, Copyright — dunkler Hintergrund
PFLICHT-IDs: id="leistungen", id="ueber-uns", id="team", id="kontakt"

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
