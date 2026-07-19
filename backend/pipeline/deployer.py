from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Build, BuildVersion
from services import r2_client
from config import settings


async def deploy(build_id: int, html: str, db: AsyncSession,
                 refinement_prompt: str | None = None) -> str:
    result = await db.execute(select(Build).where(Build.id == build_id))
    build = result.scalar_one()

    slug = build.slug
    version = (build.current_version or 0) + 1

    # HTML hochladen: versioniert + latest
    versioned_key = f"demos/{slug}/v{version}/index.html"
    latest_key = f"demos/{slug}/latest/index.html"

    r2_client.upload_html(html, versioned_key)
    r2_client.upload_html(html, latest_key)

    html_url = f"{settings.R2_PUBLIC_URL}/{versioned_key}"

    # BuildVersion erstellen
    bv = BuildVersion(
        build_id=build_id,
        version=version,
        html_url=html_url,
        refinement_prompt=refinement_prompt,
    )
    db.add(bv)

    public_url = f"{settings.DEMO_DOMAIN}/{slug}"
    build.current_version = version
    build.public_url = public_url
    build.status = "done"
    build.status_detail = None

    await db.commit()
    return public_url
