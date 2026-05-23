"""Browser-driven login for store.godotengine.org via Playwright.

The store uses Keycloak OIDC (``sso.godotengine.org``) with reCAPTCHA in some
flows. We can't relay reCAPTCHA, so this opens a real Chromium window the user
completes the login in. Once the OIDC handshake finishes and the user lands
back on a ``store.godotengine.org`` page (not ``/login`` or ``/auth``), we
read the ``session`` cookie out of the browser context, persist it, and close
the window.
"""

from __future__ import annotations

import asyncio
import contextlib
from urllib.parse import urlparse

from godot_store_mcp import config

LOGIN_URL = "https://store.godotengine.org/login"
STORE_HOST = "store.godotengine.org"


def _playwright_install_hint() -> str:
    return (
        "Playwright is not installed or its browsers are missing. Install with:\n"
        "    pip install playwright\n"
        "    python -m playwright install chromium"
    )


async def interactive_login(timeout_seconds: int = 600) -> dict:
    """Open a Chromium window, wait for login, capture the session cookie."""
    try:
        from playwright.async_api import (  # type: ignore[import-not-found]
            TimeoutError as PWTimeoutError,
        )
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError(_playwright_install_hint()) from e

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=False)
        except Exception as e:
            raise RuntimeError(
                f"Failed to launch Chromium: {e}\n\n{_playwright_install_hint()}"
            ) from e
        context = await browser.new_context()
        page = await context.new_page()
        with contextlib.suppress(PWTimeoutError):
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")

        deadline = asyncio.get_event_loop().time() + timeout_seconds
        captured_cookie: str | None = None
        try:
            while asyncio.get_event_loop().time() < deadline:
                # Detect successful login: we're back on store.godotengine.org,
                # NOT on /login or /auth, AND a session cookie exists.
                current = page.url
                parsed = urlparse(current)
                if parsed.hostname == STORE_HOST and not parsed.path.startswith(
                    ("/login", "/auth")
                ):
                    cookies = await context.cookies(f"https://{STORE_HOST}/")
                    for c in cookies:
                        if c.get("name") == "session":
                            captured_cookie = c.get("value")
                            break
                    if captured_cookie:
                        break
                # Detect if the user closed the page/browser early.
                if page.is_closed():
                    raise RuntimeError("Login window closed before authentication completed.")
                await asyncio.sleep(0.5)
        finally:
            await context.close()
            await browser.close()

    if not captured_cookie:
        raise TimeoutError(
            f"Timed out after {timeout_seconds}s waiting for login. "
            "Re-run the tool and finish the Keycloak flow in the browser window."
        )

    creds = config.load()
    creds.store.session_cookie = captured_cookie
    path = config.save(creds)
    return {
        "authenticated": True,
        "credentials_path": str(path),
        "cookie_prefix": captured_cookie[:24] + "…",
    }
