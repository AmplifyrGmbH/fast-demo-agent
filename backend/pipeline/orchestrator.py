import json
import asyncio
from sqlalchemy import select

from database import AsyncSessionLocal
from models import Build, BuildVersion
from pipeline.scraper import scrape_domain
from pipeline.analyst import run_analyst
from pipeline.builder import run_builder
from pipeline.evaluator import run_evaluator
from pipeline.deployer import deploy
from services import r2_client
from services.claude_client import call_claude, MODEL_SONNET
from pipeline.builder import extract_html
from services.image_search import fetch_hero_image


async def run_full_pipeline(build_id: int) -> None:
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(Build).where(Build.id == build_id))
            build = result.scalar_one()

            await scrape_domain(build.domain, build_id, db)
            plan = await run_analyst(build_id, db)

            # Unsplash-Fallback: kein passendes Hero-Bild vorhanden?
            result = await db.execute(select(Build).where(Build.id == build_id))
            build = result.scalar_one()
            hero = next((s for s in plan.get("sektionen", []) if s.get("typ") == "hero"), None)
            if hero and not hero.get("bild_url"):
                build.status_detail = "Hero-Bild suchen..."
                await db.commit()
                r2_url = await fetch_hero_image(plan, build_id)
                if r2_url:
                    hero["bild_url"] = r2_url
                    hero["hintergrund"] = "bild"
                    build.plan = plan
                    await db.commit()

            html = await run_builder(build_id, db)

            for round_num in range(2):
                eval_result = await run_evaluator(build_id, html, db)
                if eval_result.get("ok"):
                    break
                fixes = "\n".join(eval_result.get("fixes", []))
                result = await db.execute(select(Build).where(Build.id == build_id))
                build = result.scalar_one()
                build.status_detail = f"Evaluator: {round_num + 1}. Korrektur-Runde"
                await db.commit()
                html = await run_builder(build_id, db, fix_instructions=fixes)

            await deploy(build_id, html, db)

        except Exception as e:
            async with AsyncSessionLocal() as err_db:
                err_result = await err_db.execute(select(Build).where(Build.id == build_id))
                err_build = err_result.scalar_one()
                err_build.status = "error"
                err_build.error_log = str(e)
                await err_db.commit()


async def run_refinement(build_id: int, refinement_prompt: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(Build).where(Build.id == build_id))
            build = result.scalar_one()

            build.status = "building"
            build.status_detail = "Refinement läuft..."
            await db.commit()

            # Neueste Version laden
            versions_result = await db.execute(
                select(BuildVersion)
                .where(BuildVersion.build_id == build_id)
                .order_by(BuildVersion.version.desc())
            )
            latest_version = versions_result.scalars().first()

            if not latest_version:
                raise RuntimeError("Keine bestehende Version gefunden")

            # HTML von R2 laden
            slug = build.slug
            version_num = latest_version.version
            r2_key = f"demos/{slug}/v{version_num}/index.html"
            current_html_bytes = r2_client.download_bytes(r2_key)
            current_html = current_html_bytes.decode("utf-8")

            plan_json = json.dumps(build.plan or {}, ensure_ascii=False, indent=2)

            prompt = f"""Du bekommst eine bestehende HTML-Website und einen Anpassungswunsch.
Passe die Website gezielt an — ändere nur was notwendig ist, bewahre alles andere.

ORIGINALER BAUPLAN:
{plan_json}

ANPASSUNGSWUNSCH:
{refinement_prompt}

AKTUELLE HTML-DATEI:
{current_html}

Gib NUR die vollständige, angepasste HTML-Datei aus. Kein anderer Text."""

            response = await asyncio.to_thread(call_claude, prompt, 16000, "", MODEL_SONNET, True)
            new_html = extract_html(response)

            await deploy(build_id, new_html, db, refinement_prompt=refinement_prompt)

        except Exception as e:
            async with AsyncSessionLocal() as err_db:
                err_result = await err_db.execute(select(Build).where(Build.id == build_id))
                err_build = err_result.scalar_one()
                err_build.status = "error"
                err_build.error_log = str(e)
                await err_db.commit()
