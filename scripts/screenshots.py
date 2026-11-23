"""Phone-size screenshots of the Mini App in DEV_MODE."""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8081"
OUT = Path("/workspace/vidtg/screens")
OUT.mkdir(parents=True, exist_ok=True)
UID = "643246726"


async def shot(page, name, url, wait_for=None, extra=None):
    await page.goto(url, wait_until="networkidle")
    await page.wait_for_timeout(800)
    if wait_for:
        await page.wait_for_selector(wait_for, timeout=8000)
    if extra:
        await extra(page)
    # give video a moment to paint a frame
    await page.wait_for_timeout(1200)
    path = OUT / name
    await page.screenshot(path=str(path), type="png")
    print("wrote", path, path.stat().st_size)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="chrome",
            args=["--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream"],
        )
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        )
        page = await context.new_page()

        await shot(page, "feed.png", f"{BASE}/?uid={UID}&v=2", wait_for=".slide video")

        async def open_comments(p):
            # screen=comments already opens the sheet; wait until it is visible
            await p.wait_for_selector(".sheet.open .citem, .sheet.open .grid-empty", timeout=8000)

        await shot(page, "comments.png", f"{BASE}/?uid={UID}&v=2&startapp=v_1&screen=comments",
                   wait_for=".sheet.open", extra=open_comments)

        await shot(page, "profile.png", f"{BASE}/?uid={UID}&v=2&screen=profile&user=900001",
                   wait_for=".profile-head")

        await shot(page, "upload.png", f"{BASE}/?uid={UID}&v=2&screen=upload",
                   wait_for="#page-upload:not(.hidden)")

        await browser.close()

asyncio.run(main())
