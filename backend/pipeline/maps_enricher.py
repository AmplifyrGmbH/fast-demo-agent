import asyncio
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Build
from services.apify_client import search_google_maps


def extract_company_info(scraped_text: str, domain: str) -> tuple[str, str]:
    """Firmenname und Ort aus gescraptem Text extrahieren."""
    lines = scraped_text.split("\n")

    # Firmenname: kürzeste H1 nehmen (max 5 Wörter), sonst Domain
    firmenname = ""
    h1_candidates = [
        line.replace("[H1]", "").strip()
        for line in lines if line.startswith("[H1]")
    ]
    # Bevorzuge kürzere H1s (max 5 Wörter = wahrscheinlich Firmenname, nicht Slogan)
    for candidate in sorted(h1_candidates, key=lambda x: len(x.split())):
        if 1 <= len(candidate.split()) <= 6:
            firmenname = candidate
            break

    if not firmenname:
        # Aus Domain ableiten
        domain_clean = domain.replace("www.", "").split(".")[0]
        firmenname = domain_clean.replace("-", " ").replace("_", " ").title()

    # Sicherheitsnetz: max 40 Zeichen
    firmenname = firmenname[:40]

    # Ort: Suche nach PLZ-Pattern (Schweizer PLZ: 4-stellig)
    ort = ""
    plz_pattern = re.compile(r'\b(\d{4})\s+([A-ZÄÖÜa-zäöü][a-zäöü]+(?:\s[A-Za-zäöü]+)?)')
    for line in lines:
        match = plz_pattern.search(line)
        if match:
            ort = match.group(2).strip()
            break

    return firmenname, ort[:50]


def is_similar_name(name1: str, name2: str) -> bool:
    """Prüft ob zwei Namen ähnlich sind."""
    n1 = re.sub(r'\W+', ' ', name1.lower()).strip()
    n2 = re.sub(r'\W+', ' ', name2.lower()).strip()
    words1 = set(n1.split())
    words2 = set(n2.split())
    if not words1 or not words2:
        return False
    overlap = words1 & words2
    return len(overlap) / max(len(words1), len(words2)) > 0.3


async def enrich_with_maps(build_id: int, db: AsyncSession) -> dict:
    result = await db.execute(select(Build).where(Build.id == build_id))
    build = result.scalar_one()
    build.status_detail = "Google Maps suchen..."
    await db.commit()

    try:
        firmenname, ort = extract_company_info(build.scraped_text or "", build.domain)
        query = f"{firmenname} {ort} Schweiz".strip()

        items = await asyncio.to_thread(search_google_maps, query, 3)

        maps_data = None
        for item in items:
            item_name = item.get("title", "")
            item_rating = item.get("totalScore", 0) or 0
            if item_rating > 0 and is_similar_name(firmenname, item_name):
                # Bewertungen extrahieren
                reviews_raw = item.get("reviews", []) or []
                bewertungen = []
                for r in reviews_raw[:5]:
                    text = r.get("text", "") or r.get("textTranslated", "")
                    if text:
                        bewertungen.append({
                            "autor": r.get("name", "Anonym"),
                            "sterne": r.get("stars", 5),
                            "text": text[:300],
                        })

                # Öffnungszeiten
                opening = item.get("openingHours", []) or []

                # Fotos
                fotos = []
                for photo in (item.get("imageUrls", []) or [])[:3]:
                    if isinstance(photo, str):
                        fotos.append(photo)
                    elif isinstance(photo, dict):
                        fotos.append(photo.get("url", ""))

                maps_data = {
                    "name": item_name,
                    "rating": round(float(item_rating), 1),
                    "anzahl_bewertungen": item.get("reviewsCount", 0),
                    "bewertungen": bewertungen,
                    "oeffnungszeiten": opening,
                    "adresse": item.get("address", ""),
                    "telefon": item.get("phone", ""),
                    "fotos": [f for f in fotos if f],
                }
                break

        if maps_data:
            build.maps_found = True
            build.maps_data = maps_data
        else:
            build.maps_found = False
            build.maps_data = None

    except Exception as e:
        build.maps_found = False
        build.maps_data = None

    build.status = "analysing"
    build.status_detail = None
    await db.commit()

    return build.maps_data or {}
