"""Optional headless rendering for JavaScript-built problem pages.

Uses Playwright's Chromium when installed (``uv sync --extra browser`` then
``.venv/bin/playwright install chromium``). Every browser request is checked
against the run's origin grant; anything else is aborted, so scripts on the
page cannot widen the network scope. Only the rendered DOM is returned; file
downloads still go through the bounded SafeHTTP client.
"""
from __future__ import annotations

import importlib.util
import os
from collections.abc import Callable
from typing import Any

from metis.core.ctf_http import origin

MAX_HTML = 4 * 1_048_576


def available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def render(url: str, allowed_origins: list[str], *, cookies: list[dict[str, Any]] | None = None,
           timeout_seconds: float = 20.0) -> tuple[str, str, list[str]]:
    """Return (final_url, rendered_html, blocked_origins)."""
    if not available():
        raise RuntimeError("JavaScript rendering requires the optional 'browser' extra (Playwright)")
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

    allowed = {origin(value) for value in allowed_origins}
    blocked: set[str] = set()

    def permitted(target: str) -> bool:
        if target.startswith(("data:", "blob:", "about:")):
            return True
        try:
            return origin(target) in allowed
        except ValueError:
            return False

    def route(handler_route: Any, request: Any) -> None:
        if permitted(request.url):
            handler_route.continue_()
        else:
            try:
                blocked.add(origin(request.url))
            except ValueError:
                blocked.add("invalid-url")
            handler_route.abort()

    with sync_playwright() as playwright:
        # METIS_CHROMIUM may point at an already installed Chromium build.
        executable = os.environ.get("METIS_CHROMIUM") or None
        browser = playwright.chromium.launch(executable_path=executable)
        try:
            context = browser.new_context(accept_downloads=False, java_script_enabled=True,
                                          service_workers="block")
            if cookies:
                context.add_cookies(cookies)  # type: ignore[arg-type]
            context.route("**/*", route)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=min(10.0, timeout_seconds) * 1000)
            except Exception:  # noqa: BLE001, S110 -- long-polling pages may never go idle.
                pass
            final_url = page.url
            if not permitted(final_url):
                raise ValueError("rendered page navigated outside the authorized scope")
            html = page.content()
        finally:
            browser.close()
    if len(html.encode()) > MAX_HTML:
        raise ValueError("rendered page exceeds limit")
    return final_url, html, sorted(blocked)


Renderer = Callable[..., tuple[str, str, list[str]]]
