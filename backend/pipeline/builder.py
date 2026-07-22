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

━━━ SVG-ICONS (KEINE Emojis) ━━━
Alle Icons als Lucide-Stil inline SVG: viewBox="0 0 24 24" stroke="currentColor"
fill="none" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
Icon-Grösse im Nav: width="18" height="18" — Icon-Pfade für die verfügbaren Namen:
phone: <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07A19.5 19.5 0 013.07 9.81 19.79 19.79 0 01.22 1.18 2 2 0 012.22 0h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L6.91 7.09a16 16 0 006 6l.56-.56a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 14.92z"/>
mail: <rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 01-2.06 0L2 7"/>
map-pin: <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0116 0z"/><circle cx="12" cy="10" r="3"/>
clock: <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
users: <path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>
star: <polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26"/>
shield: <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
heart: <path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z"/>
home: <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9,22 9,12 15,12 15,22"/>
briefcase: <rect width="20" height="14" x="2" y="7" rx="2"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/>
settings: <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>
bar-chart: <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>
file-text: <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>
wrench: <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/>
camera: <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/>
zap: <polygon points="13,2 3,14 12,14 11,22 21,10 12,10"/>
award: <circle cx="12" cy="8" r="6"/><path d="M15.477 12.89L17 22l-5-3-5 3 1.523-9.11"/>
scissors: <circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/>
truck: <rect width="16" height="13" x="1" y="3" rx="2"/><path d="M16 8h4l3 5v3h-7V8z"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>
coffee: <path d="M18 8h1a4 4 0 010 8h-1"/><path d="M2 8h16v9a4 4 0 01-4 4H6a4 4 0 01-4-4V8z"/><line x1="6" y1="1" x2="6" y2="4"/><line x1="10" y1="1" x2="10" y2="4"/><line x1="14" y1="1" x2="14" y2="4"/>
utensils: <line x1="3" y1="2" x2="3" y2="22"/><path d="M7 2v6a4 4 0 01-4 4"/><path d="M21 2l-6 6.5a2 2 0 000 2.83L21 16V2z"/>
stethoscope: <path d="M4.8 2.3A.3.3 0 105 2H4a2 2 0 00-2 2v5a6 6 0 006 6 6 6 0 006-6V4a2 2 0 00-2-2h-1a.2.2 0 10.3.3"/><path d="M8 15v1a6 6 0 006 6 6 6 0 006-6v-4"/><circle cx="20" cy="10" r="2"/>
graduation-cap: <path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/>
leaf: <path d="M11 20A7 7 0 014 8.94M4 16.46V8h8a7 7 0 017 7 4.83 4.83 0 01-4.83 4.83c-3.17 0-4.17-1-4.17-1"/>
globe: <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/>
credit-card: <rect width="22" height="16" x="1" y="4" rx="2"/><line x1="1" y1="10" x2="23" y2="10"/>
package: <line x1="16.5" y1="9.4" x2="7.5" y2="4.21"/><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 002 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><polyline points="3.27,6.96 12,12.01 20.73,6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>
search: <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
lock: <rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
sun: <circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
droplets: <path d="M7 16.3c2.2 0 4-1.83 4-4.05 0-1.16-.57-2.26-1.71-3.19S7.29 6.75 7 5.3c-.29 1.45-1.14 2.84-2.29 3.76S3 11.1 3 12.25c0 2.22 1.8 4.05 4 4.05z"/><path d="M12.56 6.6A10.97 10.97 0 0114 3.02c.5 2.5 2 4.9 4 6.5s3 3.5 3 5.5a6.98 6.98 0 01-11.91 4.97"/>
palette: <circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 011.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>
music: <path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>
book: <path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/>

Nicht-gelistetes Icon → phone als Fallback verwenden.

━━━ LEISTUNGEN — SIDEBAR-TABS LAYOUT (PFLICHT) ━━━
Die Leistungen-Sektion IMMER als Sidebar-Navigation umsetzen:

HTML-Struktur:
<section id="leistungen" class="fade-in" style="background:[section_bg]">
  <div class="container">
    <h2 class="section-title">[titel]</h2>
    <div class="leistungen-wrapper">
      <ul class="leistungen-nav">
        [für jedes item:]
        <li class="[active wenn erstes]" data-panel="lp-[index]">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"
               stroke-linecap="round" stroke-linejoin="round" width="18" height="18">
            [icon-pfad aus obiger Liste]
          </svg>
          <span>[item.titel]</span>
        </li>
      </ul>
      <div class="leistungen-panels">
        [für jedes item:]
        <div class="leistungen-panel [active wenn erstes]" id="lp-[index]">
          <h3>[item.titel]</h3>
          <p>[item.beschreibung]</p>
        </div>
      </div>
    </div>
  </div>
</section>

CSS für Sidebar-Tabs:
.leistungen-wrapper {{ display:grid; grid-template-columns:260px 1fr;
  background:#fff; border-radius:16px; overflow:hidden;
  box-shadow:0 2px 20px rgba(0,0,0,.06); min-height:360px; }}
.leistungen-nav {{ list-style:none; border-right:1px solid #e5e7eb; padding:8px 0; }}
.leistungen-nav li {{ display:flex; align-items:center; gap:12px; padding:14px 20px;
  cursor:pointer; color:#6b7280; font-size:.9rem; border-left:3px solid transparent;
  transition:all .15s; }}
.leistungen-nav li.active {{ border-left-color:[primary_color]; background:#f8fafc;
  color:#111827; font-weight:600; }}
.leistungen-nav li:hover:not(.active) {{ background:rgba(0,0,0,.02); color:#374151; }}
.leistungen-panels {{ padding:36px; }}
.leistungen-panel {{ display:none; }}
.leistungen-panel.active {{ display:block; }}
.leistungen-panel h3 {{ font-size:1.6rem; font-weight:700; margin-bottom:16px; color:#111827; }}
.leistungen-panel p {{ color:#6b7280; line-height:1.75; font-size:1rem; }}
@media(max-width:767px) {{
  .leistungen-wrapper {{ grid-template-columns:1fr; }}
  .leistungen-nav {{ display:flex; overflow-x:auto; border-right:none;
    border-bottom:1px solid #e5e7eb; padding:4px; gap:2px; }}
  .leistungen-nav li {{ border-left:none; border-bottom:3px solid transparent;
    padding:10px 14px; flex-shrink:0; justify-content:center; border-radius:6px; }}
  .leistungen-nav li span {{ display:none; }}
  .leistungen-nav li.active {{ border-bottom-color:[primary_color]; border-left-color:transparent; }}
  .leistungen-panels {{ padding:24px 16px; }}
}}

JS für Tab-Switching (in den <script>-Block aufnehmen):
document.querySelectorAll('.leistungen-nav li').forEach(li => {{
  li.addEventListener('click', () => {{
    const w = li.closest('.leistungen-wrapper');
    w.querySelectorAll('.leistungen-nav li').forEach(l => l.classList.remove('active'));
    w.querySelectorAll('.leistungen-panel').forEach(p => p.classList.remove('active'));
    li.classList.add('active');
    document.getElementById(li.dataset.panel).classList.add('active');
  }});
}});

━━━ SECTION-LAYOUTS (für andere Sektionstypen) ━━━
image-left / image-right: 50/50 Split, Bild und Text
centered-text: Zentrierter Textblock, max 700px Breite

━━━ SECTION-HINTERGRÜNDE (plan.sektionen[].section_bg verwenden) ━━━
white: #ffffff
light: #f8fafc (oder stilpassend: #fef9f5 bei warm, etc.)
primary: Primärfarbe aus plan — helle Schrift
dark: #0f172a oder ähnlich — weisse Schrift

━━━ HERO (PFLICHT-QUALITÄT — hier entscheidet sich der erste Eindruck) ━━━
- position:relative, min-height:100vh, display:flex, flex-direction:column,
  align-items:center, justify-content:center, text-align:center, overflow:hidden
- hintergrund="bild": <img> mit position:absolute, inset:0, width:100%, height:100%,
  object-fit:cover, z-index:0 — PFLICHT: Overlay-div position:absolute, inset:0,
  background:rgba(0,0,0,0.52), z-index:1 — Text-Container z-index:2
- hintergrund="gradient": background:linear-gradient(135deg, [primary] 0%, [primary-20%dunkler] 100%)
  Keine Bild-Tags. Helle Schrift auf dem Gradient.
- hintergrund="dark": background:#0f172a, helle Schrift, Primärfarbe als Akzent-Element
- Hero-Inhalt: H1 min. 3.5rem, font-weight:800, line-height:1.15, max-width:800px
  Subtext: font-size:1.15rem, max-width:580px, opacity:0.92, margin:1.5rem auto
  CTA-Button: display:inline-block, padding:18px 48px, font-size:1.1rem,
  font-weight:700, border-radius per plan.design.button_style — muss auf dem Hero-BG kontrastieren
- VERBOTEN im Hero: Logo als grosses Element, Öffnungszeiten, Kontaktdaten,
  Leistungslisten, Website-Screenshot als Bild

━━━ MOBILE (PFLICHT — wird auf dem Smartphone geprüft) ━━━
Basis (Mobile-first, gilt ohne @media):
  - Section-Padding: 64px 20px
  - Font-Size body: 16px
  - Bilder: max-width:100%, height:auto
  - Grid: standardmässig 1 Spalte

@media (min-width: 768px) — Tablet/Desktop-Erweiterungen:
  - Section-Padding: 100px 40px
  - Hero H1: 3.5rem+ (Mobile-Basis: 2.2rem)
  - cards-3: grid-template-columns: repeat(3, 1fr)
  - cards-4: grid-template-columns: repeat(4, 1fr) → auf Tablet repeat(2,1fr)
  - image-left/right: display:flex, gap:60px, align-items:center (Mobile: block, Bild oben)
  - Nav-Links sichtbar, Hamburger versteckt (display:none)

Mobile-spezifisch (@media max-width:767px):
  - Hero: min-height:88vh | H1: 2.2rem | Subtext: 0.95rem | CTA: padding:14px 32px
  - cards-4: grid-template-columns: repeat(2,1fr)
  - Header: kompakter (padding:12px 20px)
  - Hamburger: sichtbar — Nav-Links als Dropdown (position:absolute, full-width)

━━━ CONTENT-ANFORDERUNGEN ━━━
- ALLE Inhalte aus dem Bauplan — kein Platzhalter, kein Lorem ipsum
- Echte Texte, Namen, Telefonnummern, Adressen
- LOGO: plan.logo_url vorhanden → <img src="logo_url"> im Header, max-height:50px. Kein Emoji-Ersatz.
- Keine Emojis — ausschliesslich SVG-Icons aus der obigen Icon-Liste

━━━ ANIMATIONEN ━━━
- Smooth Scroll: html {{ scroll-behavior: smooth; }}
- Fade-in: .fade-in {{ opacity:0; transform:translateY(24px); transition:opacity .6s,transform .6s; }}
         .fade-in.visible {{ opacity:1; transform:none; }}
  IntersectionObserver beobachtet alle .fade-in Elemente (threshold:0.15)
- Hover auf Cards: transform:translateY(-4px), Schatten verstärken
- Hover auf Buttons: leichte Aufhellung + leichter Schatten
- Header: beim Scrollen leicht verkleinern (scrolled-Klasse via JS) — subtil

━━━ SEO & META ━━━
Im <head> PFLICHT:
- <meta name="description" content="[2 Sätze: Firma + Hauptleistung + Ort]">
- <meta property="og:title" content="[Firmenname]">
- <meta property="og:description" content="[gleich wie description]">
- <meta property="og:type" content="website">
- <meta name="robots" content="index, follow">
- <link rel="canonical" href="[aktuelle URL wenn bekannt, sonst weglassen]">

━━━ KONTAKT-SEKTION (id="kontakt") ━━━
Enthält IMMER beides nebeneinander (2-Spalten auf Desktop, 1-Spalte Mobile):
Linke Spalte: Adresse, Telefon, E-Mail, Öffnungszeiten (falls vorhanden)
Rechte Spalte: Kontaktformular mit:
  <form> mit Feldern: Name (text), E-Mail (email), Nachricht (textarea, 4 Zeilen), Absenden-Button
  action="#" method="POST" — kein Backend nötig
  Felder mit placeholder und required-Attribut
  Button in Primärfarbe, gleicher Stil wie CTA-Button

━━━ STRUKTUR ━━━
1. <head>: Charset, Viewport, Title, Google Fonts Link, SEO-Meta-Tags, <style>
2. <header>: Logo + Firmenname, Nav mit Anchor-Links, Hamburger Mobile — sticky
3. <main>: Hero zuerst, dann Sektionen aus Bauplan — jede mit class="fade-in"
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
