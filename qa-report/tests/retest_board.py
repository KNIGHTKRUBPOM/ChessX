from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


root = Path(__file__).resolve().parents[2]
dist = root / (sys.argv[1] if len(sys.argv) > 1 else "dist")


class QuietServer(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


with ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietServer, directory=dist)) as server:
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    with tempfile.TemporaryDirectory(dir=root / "qa-report" / "evidence" / "post-fix") as profile, sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            profile, headless=True,
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            args=["--disable-background-networking", "--disable-component-update", "--disable-sync",
                  "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"],
        )
        try:
            page = context.pages[0]
            context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(origin + "/") else route.abort())
            requests = []
            browser_errors = []
            page.on("request", lambda event: requests.append(urlsplit(event.url).path))
            page.on("pageerror", lambda error: browser_errors.append(str(error)))
            page.goto(origin, wait_until="networkidle")
            assert not any("phaser-" in path for path in requests), requests
            page.locator('input[name="mode"][value="hybrid"]').check()
            page.get_by_role("button", name="Play", exact=True).click()
            expect(page.locator("#board canvas")).to_be_visible()
            assert sum("phaser-" in path for path in requests) == 1, requests

            def tile(coordinate):
                page.locator(f'[data-coordinate="{coordinate}"]').focus()
                page.keyboard.press("Enter")

            for coordinate in ("a2", "d2", "c2", "b2"):
                tile(coordinate)
            page.locator('[data-action="confirm"]').click()
            page.locator('[data-action="black"]').click()
            for coordinate in ("a7", "b8", "e7", "b6", "b6"):
                tile(coordinate)
            page.locator('[data-action="confirm"]').click()
            for coordinate in ("b2", "b4", "b6", "a5", "b4", "a5"):
                tile(coordinate)
            expect(page.locator("#duel-grid canvas")).to_be_visible()

            def cell(index):
                return page.locator(f'[data-cell="{index}"]')

            cell(1).focus()
            page.keyboard.press("Enter")
            expect(cell(1)).to_be_focused()
            expect(cell(1)).to_have_attribute("aria-disabled", "true")
            expect(cell(1)).to_have_attribute("data-mark", "X")
            page.keyboard.press("Enter")
            assert page.locator('#duel-grid [data-mark="X"]').count() == 1
            page.keyboard.press("ArrowLeft")
            expect(cell(0)).to_be_focused()
            page.keyboard.press("ArrowRight")
            expect(cell(1)).to_be_focused()
            page.keyboard.press("ArrowRight")
            expect(cell(2)).to_be_focused()
            page.keyboard.press("ArrowDown")
            expect(cell(5)).to_be_focused()
            page.keyboard.press("Enter")
            expect(cell(5)).to_have_attribute("data-mark", "O")
            assert not browser_errors, browser_errors
            print("PASS: no Phaser request before Play, board canvas loaded once, XO occupied cells retain focus and reject moves, arrows keep their direction.")
        finally:
            context.close()
    server.shutdown()
    server_thread.join()

