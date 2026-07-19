from playwright.async_api import async_playwright


async def take_screenshot(url: str, width: int = 1280, height: int = 800) -> bytes:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": width, "height": height})
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        screenshot = await page.screenshot(type="jpeg", quality=85)
        await browser.close()
        return screenshot


async def get_page_html(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        html = await page.content()
        await browser.close()
        return html
