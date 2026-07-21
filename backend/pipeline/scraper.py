import re
import asyncio
import base64
import aiohttp
import anthropic
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Build
from services import r2_client, screenshot_client
from config import settings
from services.claude_client import MODEL_HAIKU


async def jina_get_text(url: str, fallback_html: str = "") -> str:
    """
    Holt sauberen Markdown-Text via Jina Reader (r.jina.ai).
    Fallback auf clean_html_to_text() falls Jina nicht erreichbar ist.
    """
    headers = {"Accept": "text/plain", "X-No-Cache": "true"}
    if settings.JINA_API_KEY:
        headers["Authorization"] = f"Bearer {settings.JINA_API_KEY}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://r.jina.ai/{url}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    # Jina fügt Metadaten-Header ein — ab "=" Linien wegschneiden
                    lines = text.splitlines()
                    content_lines = [l for l in lines if not l.startswith("URL Source:") and not l.startswith("Title:")]
                    return "\n".join(content_lines).strip()
    except Exception:
        pass

    # Fallback
    return clean_html_to_text(fallback_html) if fallback_html else ""


def normalize_url(domain: str) -> str:
    if not domain.startswith("http"):
        domain = "https://" + domain
    return domain.rstrip("/")


def clean_html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "svg", "noscript", "nav", "footer", "head"]):
        tag.decompose()

    lines = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        text = el.get_text(separator=" ", strip=True)
        if len(text) > 20:
            tag_name = el.name
            if tag_name in ["h1", "h2", "h3", "h4"]:
                lines.append(f"[{tag_name.upper()}] {text}")
            else:
                lines.append(text)

    seen = set()
    unique_lines = []
    for line in lines:
        if line not in seen and len(line.strip()) > 0:
            seen.add(line)
            unique_lines.append(line)

    return "\n".join(unique_lines[:300])


def find_subpage_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    keywords = ["über", "uber", "team", "leistungen", "service", "praxis",
                 "about", "kontakt", "contact", "angebot", "behandlung"]
    links = set()
    base_domain = urlparse(base_url).netloc
    base_path = base_url.rstrip("/")

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = (a.get_text() + " " + href).lower()
        if any(kw in text for kw in keywords):
            full_url = urljoin(base_url, href).rstrip("/")
            parsed = urlparse(full_url)
            if parsed.netloc == base_domain and parsed.scheme in ["http", "https"]:
                if full_url != base_path:
                    links.add(full_url)

    return list(links)[:4]


def extract_image_urls(html: str, base_url: str, exclude_url: str | None = None) -> list[str]:
    """Gibt Bild-URLs zurück — src, srcset und data-src werden ausgewertet."""
    soup = BeautifulSoup(html, "html.parser")
    urls = []

    for img in soup.find_all("img"):
        candidates = []
        # src
        src = img.get("src", "")
        if src and not src.startswith("data:"):
            candidates.append(src)
        # data-src (lazy loading)
        data_src = img.get("data-src", "") or img.get("data-lazy-src", "")
        if data_src and not data_src.startswith("data:"):
            candidates.append(data_src)
        # srcset — grösste URL nehmen (letzter Eintrag)
        srcset = img.get("srcset", "") or img.get("data-srcset", "")
        if srcset:
            parts = [p.strip().split()[0] for p in srcset.split(",") if p.strip()]
            if parts:
                candidates.append(parts[-1])  # grösste Version

        for c in candidates:
            full_url = urljoin(base_url, c).split("?")[0]  # Query-Params entfernen
            if full_url.startswith("http") and full_url != exclude_url:
                urls.append(full_url)

    return list(dict.fromkeys(urls))


def find_logo_url(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        attrs = " ".join([
            img.get("src", ""),
            img.get("alt", ""),
            " ".join(img.get("class", [])),
            img.get("id", ""),
        ]).lower()
        if "logo" in attrs:
            src = img.get("src", "")
            if src and not src.startswith("data:"):
                return urljoin(base_url, src)
    return None


def extract_primary_color(html: str) -> str | None:
    patterns = [
        r'(?:nav|header|\.navbar|\.header|button)[^{]*\{[^}]*background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,6})',
        r'background(?:-color)?\s*:\s*(#[0-9a-fA-F]{6})',
    ]
    neutral = {"#fff", "#ffffff", "#000", "#000000", "#f5f5f5",
               "#fafafa", "#eeeeee", "#e5e5e5", "#f0f0f0", "#f9f9f9"}
    for pattern in patterns:
        for color in re.findall(pattern, html, re.IGNORECASE):
            if color.lower() not in neutral:
                return color
    return None


def extract_color_from_screenshot(screenshot_bytes: bytes) -> str:
    """Fragt Claude per Vision nach der dominanten Brandfarbe."""
    try:
        cl = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        img_b64 = base64.standard_b64encode(screenshot_bytes).decode("utf-8")
        resp = cl.messages.create(
            model=MODEL_HAIKU,
            max_tokens=50,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}},
                    {"type": "text", "text": (
                        "Analysiere diesen Website-Screenshot. Nenne nur den Hex-Code der dominanten "
                        "Brandfarbe. Ignoriere Weiss, Grau, Schwarz. Antworte nur mit dem Hex-Code, z.B. #2563eb"
                    )},
                ]
            }]
        )
        match = re.search(r"#[0-9a-fA-F]{3,6}", resp.content[0].text.strip())
        if match:
            return match.group(0)
    except Exception:
        pass
    return "#2563eb"


async def download_image(session: aiohttp.ClientSession, url: str) -> bytes | None:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200 and "image" in resp.headers.get("Content-Type", ""):
                data = await resp.read()
                # Mindestgrösse 5KB — filtert Icons und Tracking-Pixel
                if len(data) >= 5000:
                    return data
    except Exception:
        pass
    return None


async def scrape_domain(domain: str, build_id: int, db: AsyncSession) -> dict:
    result = await db.execute(select(Build).where(Build.id == build_id))
    build = result.scalar_one()
    build.status = "scraping"
    build.status_detail = "Website laden..."
    await db.commit()

    base_url = normalize_url(domain)

    # Screenshot + HTML in einer einzigen Browser-Session
    screenshot_bytes, main_html = await screenshot_client.scrape_page(base_url)

    # Screenshot nach R2
    screenshot_r2_key = f"demos/{build_id}/screenshot.jpg"
    screenshot_url = r2_client.upload_bytes(screenshot_bytes, screenshot_r2_key, "image/jpeg")

    # Logo finden (vor Bilder-Extraktion, damit es ausgeschlossen werden kann)
    logo_orig = find_logo_url(main_html, base_url)

    # Unterseiten-URLs aus HTML ermitteln
    subpage_urls = find_subpage_links(main_html, base_url)

    # Text: Hauptseite + Unterseiten parallel via Jina Reader
    build.status_detail = f"Texte extrahieren ({1 + len(subpage_urls)} Seiten)..."
    await db.commit()

    all_urls = [base_url] + subpage_urls
    jina_results = await asyncio.gather(
        *[jina_get_text(url, main_html if url == base_url else "") for url in all_urls],
        return_exceptions=True,
    )

    main_text = ""
    for url, result in zip(all_urls, jina_results):
        if isinstance(result, Exception) or not result:
            continue
        if url == base_url:
            main_text = result
        else:
            main_text += f"\n\n--- Unterseite: {url} ---\n{result}"

    main_text = main_text[:15000]

    # Bilder herunterladen (Logo ausschliessen)
    all_image_urls = extract_image_urls(main_html, base_url, exclude_url=logo_orig)
    build.status_detail = "Bilder herunterladen..."
    await db.commit()

    scraped_images = []
    async with aiohttp.ClientSession() as session:
        tasks = [download_image(session, url) for url in all_image_urls[:20]]
        results = await asyncio.gather(*tasks)

    image_data_list = [(url, data) for url, data in zip(all_image_urls[:20], results) if data]
    image_data_list = sorted(image_data_list, key=lambda x: len(x[1]), reverse=True)[:10]

    for i, (orig_url, img_bytes) in enumerate(image_data_list):
        try:
            ext = "jpg"
            if orig_url.lower().endswith(".png"):
                ext = "png"
            elif orig_url.lower().endswith(".webp"):
                ext = "webp"
            content_type = "image/jpeg" if ext == "jpg" else f"image/{ext}"
            r2_key = f"demos/{build_id}/images/{i}.{ext}"
            r2_url = r2_client.upload_bytes(img_bytes, r2_key, content_type)
            scraped_images.append({"original": orig_url, "r2": r2_url})
        except Exception:
            pass

    # Logo hochladen
    logo_r2_url = None
    if logo_orig:
        async with aiohttp.ClientSession() as session:
            logo_bytes = await download_image(session, logo_orig)
        if logo_bytes:
            try:
                ext = "png" if logo_orig.lower().endswith(".png") else "jpg"
                logo_r2_key = f"demos/{build_id}/logo.{ext}"
                logo_r2_url = r2_client.upload_bytes(logo_bytes, logo_r2_key, f"image/{ext}")
            except Exception:
                pass

    # Primärfarbe: erst CSS-Regex, dann Claude Vision als Fallback
    primary_color = extract_primary_color(main_html)
    if not primary_color:
        primary_color = extract_color_from_screenshot(screenshot_bytes)

    # DB aktualisieren
    build.scraped_text = main_text
    build.scraped_images = scraped_images
    build.logo_url = logo_r2_url
    build.primary_color = primary_color
    build.screenshot_url = screenshot_url
    build.status = "analysing"
    build.status_detail = None
    await db.commit()

    return {
        "scraped_text": main_text,
        "scraped_images": scraped_images,
        "logo_url": logo_r2_url,
        "primary_color": primary_color,
        "screenshot_url": screenshot_url,
    }
