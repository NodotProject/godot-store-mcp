"""Scripted Keycloak login for store.godotengine.org.

The store front-end uses standard OIDC Authorization-Code flow against
``sso.godotengine.org`` (realm: ``master``, client: ``store``). The login form
is plain username/password with no captcha at the time of writing. This module
drives that flow with ``httpx`` and returns the resulting ``session`` cookie.

If Keycloak ever enables reCAPTCHA, 2FA, or another required action, we detect
it and raise :class:`InteractiveAuthRequired` so callers can fall back to the
browser-driven flow.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from godot_asset_store_mcp import config

LOGIN_URL = "https://store.godotengine.org/login"
STORE_HOST = "store.godotengine.org"
SSO_HOST = "sso.godotengine.org"


class LoginError(RuntimeError):
    """Generic login failure."""


class InvalidCredentials(LoginError):
    """Keycloak rejected the username/password."""


class InteractiveAuthRequired(LoginError):
    """Keycloak demands interactive input we cannot supply (captcha, 2FA, etc)."""


def _detect_interactive_block(html: str) -> str | None:
    """Return a human-readable reason if the page requires interactive auth."""
    low = html.lower()
    if "g-recaptcha" in low or "grecaptcha" in low or 'src="https://www.google.com/recaptcha' in low:
        return "Keycloak is showing a reCAPTCHA challenge."
    if 'name="otp"' in low or "one-time" in low or "authenticator" in low and "code" in low:
        return "Two-factor / OTP code required."
    if "update password" in low or "configure-totp" in low:
        return "Keycloak is requiring a required-action step (password update / TOTP setup)."
    return None


def _detect_login_error(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    alert = soup.select_one(".alert-error, .kc-feedback-text, #input-error, .pf-c-form__helper-text")
    if alert:
        text = alert.get_text(" ", strip=True)
        if text:
            return text
    if re.search(r"invalid username or password", html, re.IGNORECASE):
        return "Invalid username or password"
    return None


async def scripted_login(username: str, password: str, *, timeout: float = 30.0) -> dict:
    """Run the OIDC authorization-code flow end-to-end with httpx.

    Returns ``{"session_cookie": "...", "username": "..."}`` on success.
    """
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        # 1. Start the OIDC flow. /login 302s to Keycloak, which renders the login form.
        kc_response = await client.get(LOGIN_URL)
        if kc_response.status_code >= 400:
            raise LoginError(
                f"Could not start login flow: HTTP {kc_response.status_code} at {kc_response.url}"
            )
        kc_html = kc_response.text
        parsed_kc_url = urlparse(str(kc_response.url))
        if parsed_kc_url.hostname == STORE_HOST and parsed_kc_url.path not in ("/login", ""):
            # Already authenticated (cookie was still valid from a previous run).
            cookie = client.cookies.get("session", domain=STORE_HOST)
            if cookie:
                return _persist(username, cookie)

        block = _detect_interactive_block(kc_html)
        if block:
            raise InteractiveAuthRequired(
                f"{block} Use store_login_browser to complete it in a real browser."
            )

        soup = BeautifulSoup(kc_html, "lxml")
        form = soup.find("form", id="kc-form-login") or soup.find("form")
        if form is None or not form.get("action"):
            raise LoginError(
                "Could not locate the Keycloak login form (page layout may have changed)."
            )
        action = form["action"]
        if action.startswith("/"):
            action = f"https://{parsed_kc_url.hostname}{action}"

        # 2. Submit credentials. Keycloak responds with a 302 chain that ends back at
        #    store.godotengine.org/auth?code=… → /, and Flask sets the `session` cookie.
        form_data = {
            "username": username,
            "password": password,
            "credentialId": "",
            "login": "Sign In",
        }
        login_response = await client.post(
            action,
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        final_host = urlparse(str(login_response.url)).hostname
        # 3a. If we ended up on the store, success — read the session cookie.
        if final_host == STORE_HOST:
            cookie = client.cookies.get("session", domain=STORE_HOST)
            if not cookie:
                raise LoginError(
                    "Login appeared to succeed but no session cookie was issued; "
                    "the store may have rejected the OIDC callback."
                )
            return _persist(username, cookie)

        # 3b. Still on Keycloak — inspect the page for the failure reason.
        if final_host == SSO_HOST:
            block = _detect_interactive_block(login_response.text)
            if block:
                raise InteractiveAuthRequired(
                    f"{block} Use store_login_browser to complete it in a real browser."
                )
            err = _detect_login_error(login_response.text)
            raise InvalidCredentials(err or "Login was rejected by Keycloak.")

        raise LoginError(
            f"Unexpected redirect after login: ended on {login_response.url} (status {login_response.status_code})."
        )


def _persist(username: str, cookie: str) -> dict:
    creds = config.load()
    creds.store.session_cookie = cookie
    creds.store.username = username
    path = config.save(creds)
    return {
        "authenticated": True,
        "username": username,
        "credentials_path": str(path),
        "cookie_prefix": cookie[:24] + "…",
    }
