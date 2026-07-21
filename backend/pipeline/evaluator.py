import asyncio
import base64
import json
import re
import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Build
from services.claude_client import call_claude_multimodal, MODEL_SONNET


async def _fetch_image_b64(session: aiohttp.ClientSession, url: str) -> tuple[str, str] | None:
    """Lädt ein Bild herunter und gibt (base64, media_type) zurück."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
            if not content_type.startswith("image/"):
                return None
            data = await resp.read()
            if len(data) < 1000:
                return None
            b64 = base64.standard_b64encode(data).decode("utf-8")
            return b64, content_type
    except Exception:
        return None


async def _collect_images(plan: dict) -> list[tuple[str, str]]:
    """Sammelt bis zu 4 Schlüsselbilder aus dem Plan für die visuelle Prüfung."""
    urls = []

    # Hero-Bild
    for s in plan.get("sektionen", []):
        if s.get("typ") == "hero" and s.get("bild_url"):
            urls.append(s["bild_url"])
            break

    # Bis zu 3 weitere Inhaltsbilder
    scraped = plan.get("_scraped_images_sample", [])
    for img in scraped[:3]:
        url = img.get("r2") if isinstance(img, dict) else img
        if url and url not in urls:
            urls.append(url)

    if not urls:
        return []

    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_image_b64(session, url) for url in urls[:4]]
        results = await asyncio.gather(*tasks)

    return [r for r in results if r]


async def run_evaluator(build_id: int, html: str, db: AsyncSession) -> dict:
    result = await db.execute(select(Build).where(Build.id == build_id))
    build = result.scalar_one()
    build.status = "evaluating"
    build.status_detail = "Qualität prüfen..."
    await db.commit()

    plan = build.plan or {}
    plan_json = json.dumps(plan, ensure_ascii=False, indent=2)
    user_prompt = build.user_prompt or ""

    # Bilder für visuelle Prüfung laden
    # scraped_images in den Plan einbetten (temporär für _collect_images)
    plan_with_images = dict(plan)
    plan_with_images["_scraped_images_sample"] = build.scraped_images or []
    images_b64 = await _collect_images(plan_with_images)

    # HTML kürzen: Head/CSS (Anfang) + Body-Content (Ende)
    html_excerpt = html[:20000] + ("\n...[gekürzt]...\n" + html[-10000:] if len(html) > 20000 else "")

    bild_hinweis = f"{len(images_b64)} Bild(er) zur visuellen Prüfung beigefügt." if images_b64 else "Keine Bilder verfügbar."

    prompt = f"""Du bist ein erfahrener Web-Designer und QA-Spezialist. Prüfe diese Website-Demo
auf technische Korrektheit, Design-Qualität und Bildqualität. Antworte NUR mit JSON.

BAUPLAN (Soll-Zustand):
{plan_json}

USER-PROMPT (falls vorhanden):
{user_prompt}

HTML ZU PRÜFEN:
{html_excerpt}

BILDER: {bild_hinweis}

━━━ TECHNISCHE PRÜFPUNKTE ━━━
1. Alle Sektionen aus dem Bauplan vorhanden?
2. Platzhalter vorhanden? ("[TELEFON]", "Lorem ipsum", leere href="#", "Ihr Name", etc.)
3. Viewport-Meta-Tag vorhanden?
4. @media Breakpoints im CSS vorhanden?
5. PFLICHT-IDs vorhanden? (id="leistungen", id="ueber-uns", id="kontakt")
6. Logo korrekt eingebunden falls plan.logo_url vorhanden?
7. User-Prompt-Anforderungen erfüllt (falls vorhanden)?
8. <meta name="description"> vorhanden und sinnvoll befüllt?
9. Kontaktformular vorhanden (Felder: Name, E-Mail, Nachricht, Absenden-Button)?

━━━ DESIGN-QUALITÄT ━━━
8. section_bg abwechselnd? (nie zweimal dieselbe Hintergrundfarbe direkt hintereinander)
9. Fade-in Animation implementiert? (.fade-in Klasse + IntersectionObserver im JS)
10. Hero-Headline konkret und einprägsam? (kein generischer Firmenname als Headline)
11. Card/Element Hover-Effekte vorhanden (transform oder box-shadow)?
12. Leistungs-Icons visuell prominent (font-size mind. 2rem)?
13. Design-Stil aus Bauplan erkennbar umgesetzt (bold-modern = grosse Type + Kontrast, etc.)?
14. Footer vorhanden mit Firmeninfos?
15. Hero-Sektion sauber? NUR Headline, Subtext, CTA — keine Öffnungszeiten, Kontaktdaten oder anderen Sektionsinhalte im Hero?
16. Kein Website-Screenshot als Hero-Hintergrundbild verwendet? (Screenshot-URLs enthalten oft "screenshot.jpg" — das ist verboten)
17. Hero min-height:100vh (oder 88vh mobile) gesetzt?
18. Hero-Bild hat Overlay (rgba(0,0,0,...))? Text muss auf jedem Bild lesbar sein.
19. Mobile: @media (max-width:767px) oder Mobile-first CSS vorhanden? Cards stacken auf 1 Spalte?
20. Hero H1 font-size auf Mobile reduziert (max. 2.5rem)?

━━━ BILDQUALITÄT (falls Bilder beigefügt) ━━━
21. Hero-Bild: Querformat, professionell, thematisch passend zur Branche?
22. Bilder allgemein: gut beleuchtet, scharf, nicht pixelig?
23. Kein offensichtliches Qualitätsproblem (zu dunkel, zu klein, falsches Sujet)?
24. Passen die Bilder inhaltlich zum Unternehmen und zur Branche? (z.B. kein Bürobild bei Zahnarzt, kein Fabrikbild bei Restaurant)

Antwortformat:
{{"ok": true}}
oder
{{"ok": false, "fixes": ["konkretes Problem 1", "konkretes Problem 2"]}}

Sei streng aber fair. ok=true nur wenn technisch und gestalterisch wirklich alles stimmt.
Antworte NUR mit dem JSON-Objekt."""

    response = await asyncio.to_thread(
        call_claude_multimodal, prompt, images_b64, 3000, MODEL_SONNET
    )

    match = re.search(r'\{[\s\S]*\}', response)
    result_data = json.loads(match.group(0)) if match else {"ok": True}

    build.evaluator_rounds = (build.evaluator_rounds or 0) + 1
    build.status = "building"
    build.status_detail = None
    await db.commit()

    return result_data
