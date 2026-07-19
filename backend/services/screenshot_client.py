from playwright.async_api import async_playwright


async def scrape_page(url: str, width: int = 1280, height: int = 800) -> tuple[bytes, str]:
    """
    Lädt die URL einmal und gibt (screenshot_bytes, html) zurück.
    Spart eine Browser-Session gegenüber zwei separaten Aufrufen.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": width, "height": height})
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        screenshot = await page.screenshot(type="jpeg", quality=85)
        html = await page.content()
        await browser.close()
        return screenshot, html


async def get_page_html(url: str) -> str:
    """Lädt eine Unterseite und gibt das gerenderte HTML zurück."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        html = await page.content()
        await browser.close()
        return html
