import re
import asyncio
import aiohttp
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Build
from services import r2_client, screenshot_client
from services.claude_client import call_claude


def normalize_url(domain: str) -> str:
    if not domain.startswith("http"):
        domain = "https://" + domain
    return domain.rstrip("/")


def clean_html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "svg", "noscript", "nav", "footer", "head"]):
        tag.decompose()

    lines = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "span", "div", "a"]):
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

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = (a.get_text() + " " + href).lower()
        if any(kw in text for kw in keywords):
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            if parsed.netloc == base_domain and parsed.scheme in ["http", "https"]:
                if full_url != base_url:
                    links.add(full_url)

    return list(links)[:4]


def extract_image_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for img in soup.find_all("img", src=True):
        src = img.get("src", "")
        if src and not src.startswith("data:"):
            full_url = urljoin(base_url, src)
            if full_url.startswith("http"):
                urls.append(full_url)
    return list(dict.fromkeys(urls))


def find_logo_url(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        attrs = " ".join([
            img.get("src", ""),
            img.get("alt", ""),
            img.get("class", [""])[0] if img.get("class") else "",
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
    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for color in matches:
            lower = color.lower()
            if lower not in ["#fff", "#ffffff", "#000", "#000000", "#f5f5f5",
                              "#fafafa", "#eeeeee", "#e5e5e5", "#f0f0f0"]:
                return color
    return None


async def download_image(session: aiohttp.ClientSession, url: str) -> bytes | None:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200 and "image" in resp.headers.get("Content-Type", ""):
                return await resp.read()
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

    # Screenshot + HTML der Hauptseite
    screenshot_bytes = await screenshot_client.take_screenshot(base_url)
    main_html = await screenshot_client.get_page_html(base_url)

    # Screenshot nach R2
    screenshot_r2_key = f"demos/{build_id}/screenshot.jpg"
    screenshot_url = r2_client.upload_bytes(screenshot_bytes, screenshot_r2_key, "image/jpeg")

    # Text extrahieren
    main_text = clean_html_to_text(main_html)

    # Unterseiten
    subpage_urls = find_subpage_links(main_html, base_url)
    build.status_detail = f"Unterseiten laden ({len(subpage_urls)})..."
    await db.commit()

    for sub_url in subpage_urls:
        try:
            sub_html = await screenshot_client.get_page_html(sub_url)
            sub_text = clean_html_to_text(sub_html)
            main_text += f"\n\n--- Unterseite: {sub_url} ---\n" + sub_text
        except Exception:
            pass

    main_text = main_text[:15000]

    # Bilder
    all_image_urls = extract_image_urls(main_html, base_url)
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

    # Logo
    logo_r2_url = None
    logo_orig = find_logo_url(main_html, base_url)
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

    # Primärfarbe
    primary_color = extract_primary_color(main_html)
    if not primary_color:
        try:
            color_prompt = (
                "Analysiere diesen Website-Screenshot. Nenne nur den Hex-Code der dominanten "
                "Brandfarbe. Ignoriere Weiss, Grau, Schwarz. Antworte nur mit dem Hex-Code, z.B. #2563eb"
            )
            import anthropic as ant
            from config import settings as cfg
            cl = ant.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)
            import base64
            img_b64 = base64.standard_b64encode(screenshot_bytes).decode("utf-8")
            resp = cl.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=50,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}},
                        {"type": "text", "text": color_prompt},
                    ]
                }]
            )
            color_text = resp.content[0].text.strip()
            match = re.search(r"#[0-9a-fA-F]{3,6}", color_text)
            if match:
                primary_color = match.group(0)
        except Exception:
            primary_color = "#2563eb"

    if not primary_color:
        primary_color = "#2563eb"

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
