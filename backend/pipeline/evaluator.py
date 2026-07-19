import asyncio
import json
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Build
from services.claude_client import call_claude


async def run_evaluator(build_id: int, html: str, db: AsyncSession) -> dict:
    result = await db.execute(select(Build).where(Build.id == build_id))
    build = result.scalar_one()
    build.status = "evaluating"
    build.status_detail = "Qualität prüfen..."
    await db.commit()

    plan_json = json.dumps(build.plan or {}, ensure_ascii=False, indent=2)
    user_prompt = build.user_prompt or ""

    # HTML kürzen damit es nicht zu gross wird
    html_excerpt = html[:30000]

    prompt = f"""Überprüfe folgendes HTML auf Qualität. Antworte NUR mit JSON.

BAUPLAN (Soll-Zustand):
{plan_json}

USER-PROMPT (falls vorhanden):
{user_prompt}

HTML ZU PRÜFEN:
{html_excerpt}

PRÜFPUNKTE:
1. Alle Sektionen aus dem Bauplan vorhanden?
2. Platzhalter oder leere Felder vorhanden? (z.B. "[TELEFON]", "Lorem ipsum", leere href="#")
3. Viewport-Meta-Tag vorhanden?
4. Mobile Breakpoints im CSS vorhanden (@media)?
5. Alle Bilder-URLs korrekt (https:// URLs, kein Placeholder)?
6. User-Prompt-Anforderungen erfüllt (falls vorhanden)?

Antwortformat:
{{"ok": true}}
oder
{{"ok": false, "fixes": ["Problem 1 mit konkreter Beschreibung", "Problem 2"]}}

Sei streng: Antworte nur dann mit ok=true wenn wirklich alles stimmt.
Antworte NUR mit dem JSON-Objekt."""

    response = await asyncio.to_thread(call_claude, prompt, 1024)

    match = re.search(r'\{[\s\S]*\}', response)
    if match:
        result_data = json.loads(match.group(0))
    else:
        result_data = {"ok": True}

    build.evaluator_rounds = (build.evaluator_rounds or 0) + 1
    build.status = "building"
    build.status_detail = None
    await db.commit()

    return result_data
