"""FastMCP tools backed by ``AssetStoreClient``.

Most tools here scrape HTML — selectors may break as the beta store evolves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urljoin

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from godot_asset_store_mcp import config
from godot_asset_store_mcp.download import stream_download
from godot_asset_store_mcp.store.client import AssetStoreClient, StoreError


def _handle(err: StoreError) -> dict[str, Any]:
    return {"error": True, "status": err.status, "message": str(err)}


def _client_from_creds() -> AssetStoreClient:
    cookie = config.load().store.session_cookie
    return AssetStoreClient(session_cookie=cookie)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="store_search",
        description=(
            "Search the new Godot Asset Store (store.godotengine.org). Optionally pass a "
            "scroll cursor returned from a previous call to paginate. BETA: relies on HTML "
            "scraping; result shape may change."
        ),
    )
    async def store_search(
        query: Annotated[
            str | None,
            Field(description="Free-text query. Prefix with # to search a tag, e.g. '#3d'."),
        ] = None,
        scroll: Annotated[
            str | None,
            Field(description="Opaque scroll cursor from a previous response's `next_scroll`."),
        ] = None,
    ) -> dict:
        async with _client_from_creds() as c:
            try:
                return await c.search(query=query, scroll=scroll)
            except StoreError as e:
                return _handle(e)

    @mcp.tool(
        name="store_get_asset",
        description=(
            "Fetch the detail page for an asset on the new store, identified by publisher "
            "slug and asset slug (the two path components after /asset/). Returns title, "
            "description, tags, external links and per-version download metadata. BETA."
        ),
    )
    async def store_get_asset(publisher: str, slug: str) -> dict:
        async with _client_from_creds() as c:
            try:
                return await c.get_asset(publisher, slug)
            except StoreError as e:
                return _handle(e)

    @mcp.tool(
        name="store_list_publisher_assets",
        description="List every asset published by a given publisher slug on the new store.",
    )
    async def store_list_publisher_assets(publisher: str) -> dict:
        async with _client_from_creds() as c:
            try:
                return await c.list_publisher_assets(publisher)
            except StoreError as e:
                return _handle(e)

    # ---------------------------------------------------------------- auth

    @mcp.tool(
        name="store_login",
        description=(
            "Open a Chromium window so you can sign in to store.godotengine.org via "
            "Keycloak SSO (including any reCAPTCHA challenge). After login succeeds the "
            "tool captures the session cookie from the browser, stores it locally, and "
            "closes the window. Requires `playwright` and a one-time "
            "`python -m playwright install chromium`."
        ),
    )
    async def store_login(
        timeout_seconds: Annotated[
            int,
            Field(
                ge=30,
                le=1800,
                description="How long to wait for the user to finish logging in (seconds).",
            ),
        ] = 600,
    ) -> dict:
        from godot_asset_store_mcp.store.login import interactive_login

        try:
            return await interactive_login(timeout_seconds=timeout_seconds)
        except (RuntimeError, TimeoutError) as e:
            return {"error": True, "message": str(e)}

    @mcp.tool(
        name="store_set_session_cookie",
        description=(
            "Manually persist a `session` cookie value copied from a browser's DevTools. "
            "Useful as a fallback if `store_login` doesn't work in your environment."
        ),
    )
    async def store_set_session_cookie(
        cookie: Annotated[str, Field(description="Value of the `session` cookie.")],
        username: Annotated[str | None, Field(description="Optional label.")] = None,
    ) -> dict:
        creds = config.load()
        creds.store.session_cookie = cookie
        if username is not None:
            creds.store.username = username
        path = config.save(creds)
        return {"saved": True, "credentials_path": str(path)}

    @mcp.tool(
        name="store_logout",
        description="Clear the stored new-store session cookie locally.",
    )
    async def store_logout() -> dict:
        config.clear_store()
        return {"cleared": True}

    # -------------------------------------------------------- write actions

    @mcp.tool(
        name="store_add_to_library",
        description=(
            "Add an asset to your library on the new store (requires login). "
            "Equivalent to clicking 'Add to Library' on the asset page."
        ),
    )
    async def store_add_to_library(publisher: str, slug: str) -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.add_to_library(publisher, slug)
            except StoreError as e:
                return _handle(e)

    @mcp.tool(
        name="store_remove_from_library",
        description="Remove an asset from your library on the new store (requires login).",
    )
    async def store_remove_from_library(publisher: str, slug: str) -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.remove_from_library(publisher, slug)
            except StoreError as e:
                return _handle(e)

    # ----------------------------------------------------------- downloads

    @mcp.tool(
        name="store_download_asset",
        description=(
            "Download an asset zip from the new store. Either pass `download_id` (from "
            "store_get_asset's downloads list) or omit to take the currently-selected "
            "version. Uses the CDN direct URL when available, otherwise the in-store "
            "download endpoint (which may require login)."
        ),
    )
    async def store_download_asset(
        publisher: str,
        slug: str,
        dest_dir: str,
        download_id: Annotated[
            str | None, Field(description="Specific download id from store_get_asset.")
        ] = None,
        filename: Annotated[
            str | None, Field(description="Override filename; default uses URL/headers.")
        ] = None,
    ) -> dict:
        cookie = config.load().store.session_cookie
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                url = await c.resolve_download_url(publisher, slug, download_id)
            except StoreError as e:
                return _handle(e)
            # Use the (cookied) client for any in-store endpoint;
            # CDN URLs work fine with the same client.
            if not url.startswith("http"):
                url = urljoin(c.base_url + "/", url.lstrip("/"))
            result = await stream_download(
                url, Path(dest_dir), client=c._ensure_client(), filename=filename
            )
        return {"publisher": publisher, "slug": slug, **result}
