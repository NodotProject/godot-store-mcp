"""CLI entry point.

Run with no arguments to start the FastMCP server over stdio. Run with a
subcommand to authenticate interactively in the terminal — credentials are
prompted locally via :mod:`getpass` and never pass through an LLM:

* ``godot-store-mcp login``       — old asset library (godotengine.org/asset-library)
* ``godot-store-mcp login-store`` — new asset store (store.godotengine.org, OIDC)

Use these when your MCP client does not support interactive elicitation (so the
``library_login`` / ``store_login`` tools can't prompt you securely in-client).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="godot-store-mcp",
        description=(
            "MCP server for the Godot asset library and the new Godot Asset Store. "
            "Run with no arguments to start the MCP server over stdio."
        ),
    )
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser(
        "login",
        help=(
            "Interactively authenticate to the old asset library "
            "(godotengine.org/asset-library) and save the token locally."
        ),
    )
    sub.add_parser(
        "login-store",
        help=(
            "Interactively authenticate to the new asset store "
            "(store.godotengine.org) and save the session cookie locally."
        ),
    )
    args = parser.parse_args()

    if args.cmd == "login":
        sys.exit(asyncio.run(_cli_library_login()))
    if args.cmd == "login-store":
        sys.exit(asyncio.run(_cli_store_login()))

    # Default: run the MCP server over stdio.
    from godot_store_mcp.server import mcp

    mcp.run()


def _prompt_credentials(label: str) -> tuple[str, str] | None:
    print(f"Logging in to {label}.")
    try:
        username = input("Username: ").strip()
    except EOFError:
        print("Aborted: no input.", file=sys.stderr)
        return None
    if not username:
        print("Aborted: username required.", file=sys.stderr)
        return None
    try:
        password = getpass.getpass("Password: ")
    except EOFError:
        print("Aborted: no input.", file=sys.stderr)
        return None
    if not password:
        print("Aborted: password required.", file=sys.stderr)
        return None
    return username, password


async def _cli_library_login() -> int:
    from godot_store_mcp import config
    from godot_store_mcp.library.client import AssetLibraryClient, AssetLibraryError

    prompted = _prompt_credentials("godotengine.org/asset-library (old library)")
    if prompted is None:
        return 1
    username, password = prompted

    async with AssetLibraryClient() as c:
        try:
            result = await c.login(username, password)
        except AssetLibraryError as e:
            print(f"Login failed: HTTP {e.status} {e.payload!r}", file=sys.stderr)
            return 2

    token = result.get("token") if isinstance(result, dict) else None
    if not token:
        print(f"Login failed (no token in response): {result!r}", file=sys.stderr)
        return 2

    creds = config.load()
    creds.library.username = result.get("username") or username
    creds.library.token = token
    path = config.save(creds)
    print(f"Saved token for '{creds.library.username}' to {path}.")
    return 0


async def _cli_store_login() -> int:
    from godot_store_mcp.store.oidc import (
        InteractiveAuthRequired,
        InvalidCredentials,
        LoginError,
        scripted_login,
    )

    prompted = _prompt_credentials("store.godotengine.org (new asset store)")
    if prompted is None:
        return 1
    username, password = prompted

    try:
        result = await scripted_login(username, password)
    except InvalidCredentials as e:
        print(f"Login failed: {e}", file=sys.stderr)
        return 2
    except InteractiveAuthRequired as e:
        print(
            f"{e}\n\nTry the browser-driven flow instead:\n"
            "    pip install 'godot-store-mcp[browser]'\n"
            "    python -m playwright install chromium\n"
            "then call store_login_browser via the MCP server.",
            file=sys.stderr,
        )
        return 3
    except LoginError as e:
        print(f"Login failed: {e}", file=sys.stderr)
        return 2

    print(
        f"Saved session cookie for '{result.get('username')}' to "
        f"{result.get('credentials_path')}."
    )
    return 0


if __name__ == "__main__":
    main()
