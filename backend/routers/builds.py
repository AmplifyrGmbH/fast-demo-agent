import asyncio
import re
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models import Build, BuildVersion
from pipeline.orchestrator import run_full_pipeline, run_refinement, run_prompt_pipeline
from services import r2_client

router = APIRouter(prefix="/api/v1/builds", tags=["builds"])


def generate_slug(domain: str) -> str:
    slug = domain.lower()
    slug = slug.replace("www.", "").split("/")[0]
    slug = slug.replace(".", "-")
    slug = re.sub(r'[äÄ]', 'ae', slug)
    slug = re.sub(r'[öÖ]', 'oe', slug)
    slug = re.sub(r'[üÜ]', 'ue', slug)
    slug = re.sub(r'ß', 'ss', slug)
    slug = re.sub(r'[^a-z0-9-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug[:60]


async def unique_slug(base_slug: str, db: AsyncSession) -> str:
    slug = base_slug
    i = 2
    while True:
        result = await db.execute(select(Build).where(Build.slug == slug))
        if not result.scalar_one_or_none():
            return slug
        slug = f"{base_slug}-{i}"
        i += 1


class StartBuildRequest(BaseModel):
    domain: str
    user_prompt: Optional[str] = None


class RefineRequest(BaseModel):
    prompt: str


@router.post("/start-from-prompt")
async def start_from_prompt(
    prompt: str = Form(...),
    firmenname: str = Form(""),
    images: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
):
    firmenname = firmenname.strip()
    base_name = firmenname or prompt[:40]
    base_slug = generate_slug(base_name)
    slug = await unique_slug(base_slug, db)

    full_prompt = f"Firmenname: {firmenname}\n\n{prompt.strip()}" if firmenname else prompt.strip()

    build = Build(
        domain=None,
        slug=slug,
        user_prompt=full_prompt,
        build_type="prompt",
        status="pending",
    )
    db.add(build)
    await db.commit()
    await db.refresh(build)

    # Bilder direkt nach R2 hochladen
    uploaded = []
    for i, file in enumerate(images[:5]):
        data = await file.read()
        if not data:
            continue
        ext = (file.filename or "").rsplit(".", 1)[-1].lower()
        if ext not in ("jpg", "jpeg", "png", "webp"):
            ext = "jpg"
        content_type = file.content_type or "image/jpeg"
        r2_key = f"demos/{build.id}/uploads/{i}.{ext}"
        try:
            r2_url = r2_client.upload_bytes(data, r2_key, content_type)
            uploaded.append({"original": file.filename, "r2": r2_url})
        except Exception:
            pass

    if uploaded:
        build.scraped_images = uploaded
        await db.commit()

    asyncio.create_task(run_prompt_pipeline(build.id))
    return {"build_id": build.id}


@router.post("/start")
async def start_build(req: StartBuildRequest, db: AsyncSession = Depends(get_db)):
    domain = req.domain.strip().lower().replace("https://", "").replace("http://", "").rstrip("/")
    base_slug = generate_slug(domain)
    slug = await unique_slug(base_slug, db)

    build = Build(
        domain=domain,
        slug=slug,
        user_prompt=req.user_prompt,
        status="pending",
    )
    db.add(build)
    await db.commit()
    await db.refresh(build)

    asyncio.create_task(run_full_pipeline(build.id))

    return {"build_id": build.id}


@router.get("")
async def list_builds(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Build).order_by(Build.created_at.desc()).limit(50)
    )
    builds = result.scalars().all()
    return [
        {
            "id": b.id,
            "domain": b.domain,
            "slug": b.slug,
            "build_type": b.build_type,
            "status": b.status,
            "current_version": b.current_version,
            "public_url": b.public_url,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in builds
    ]


@router.get("/{build_id}")
async def get_build(build_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Build).where(Build.id == build_id))
    build = result.scalar_one_or_none()
    if not build:
        raise HTTPException(status_code=404, detail="Build nicht gefunden")

    versions_result = await db.execute(
        select(BuildVersion)
        .where(BuildVersion.build_id == build_id)
        .order_by(BuildVersion.version)
    )
    versions = versions_result.scalars().all()

    return {
        "id": build.id,
        "domain": build.domain,
        "slug": build.slug,
        "user_prompt": build.user_prompt,
        "status": build.status,
        "status_detail": build.status_detail,
        "current_version": build.current_version,
        "public_url": build.public_url,
        "logo_url": build.logo_url,
        "primary_color": build.primary_color,
        "screenshot_url": build.screenshot_url,
        "maps_found": build.maps_found,
        "maps_data": build.maps_data,
        "plan": build.plan,
        "evaluator_rounds": build.evaluator_rounds,
        "error_log": build.error_log,
        "created_at": build.created_at.isoformat() if build.created_at else None,
        "versions": [
            {
                "version": v.version,
                "html_url": v.html_url,
                "refinement_prompt": v.refinement_prompt,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ],
    }


@router.post("/{build_id}/refine")
async def refine_build(build_id: int, req: RefineRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Build).where(Build.id == build_id))
    build = result.scalar_one_or_none()
    if not build:
        raise HTTPException(status_code=404, detail="Build nicht gefunden")
    if build.status not in ["done", "error"]:
        raise HTTPException(status_code=400, detail="Build läuft noch")

    asyncio.create_task(run_refinement(build_id, req.prompt))
    return {"ok": True}


@router.delete("/{build_id}")
async def delete_build(build_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Build).where(Build.id == build_id))
    build = result.scalar_one_or_none()
    if not build:
        raise HTTPException(status_code=404, detail="Build nicht gefunden")
    await db.delete(build)
    await db.commit()
    return {"ok": True}


@router.websocket("/ws/{build_id}")
async def build_websocket(websocket: WebSocket, build_id: int):
    await websocket.accept()
    from database import AsyncSessionLocal
    try:
        while True:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Build).where(Build.id == build_id))
                build = result.scalar_one_or_none()

            if not build:
                await websocket.send_text(json.dumps({"error": "Build nicht gefunden"}))
                break

            payload = {
                "status": build.status,
                "status_detail": build.status_detail,
                "current_version": build.current_version,
                "public_url": build.public_url,
            }
            await websocket.send_text(json.dumps(payload))

            if build.status in ["done", "error"]:
                break

            await asyncio.sleep(2)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
