"""Browser smoke test (R2.2, point 32): every page loads without a console error, in English and Arabic.

Needs Playwright with Chromium (``pip install playwright && python -m playwright install chromium``); CI's
``browser`` job installs them. Skipped when Playwright is not installed.
"""
from __future__ import annotations

import socket
import threading
import time

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from conftest import PASSWORDS  # noqa: E402

PAGES = ["farm", "planning", "water", "crop", "greenhouses", "satellite", "regional", "maintenance", "commission", "assistant", "world", "overview", "alerts", "health", "devices", "notify", "commands", "analytics", "history", "flash", "reports",
         "org", "security", "integrations", "usage", "help",
         "admin", "system"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def server(app):
    import uvicorn

    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not srv.started and time.time() < deadline:
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=10)


@pytest.mark.parametrize("lang", ["en", "ar"])
def test_every_page_renders_without_console_errors(server, lang):
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(server + "/login")
        page.evaluate(f"localStorage.setItem('wiot.lang', '{lang}')")
        page.fill("#u", "EgSA_Supervisor")
        page.fill("#p", PASSWORDS["WIOT_SUPERVISOR_PASSWORD"])
        page.click("button[type=submit]")
        # "/**" also matches /login itself: wait until the sign-in has really completed, or the next navigation
        # cancels the sign-in request and every page lands back on the sign-in page.
        page.wait_for_url(lambda url: "/login" not in url, timeout=20000)
        page.wait_for_selector("#page > *", timeout=15000)
        for name in PAGES:
            page.goto(f"{server}/#/{name}")
            page.wait_for_selector("#page > *", timeout=15000)
            page.wait_for_timeout(400)
            assert page.locator("#page .empty").filter(has_text="Internal server error").count() == 0, name
        page.goto(server + "/status")
        page.wait_for_selector("#st-components .up-row, #st-components .empty", timeout=15000)
        # Map tiles and the weather service are unreachable in CI; ignore failed third-party loads only.
        real = [e for e in errors if "net::ERR" not in e and "Failed to load resource" not in e]
        assert not real, real
        browser.close()
