"""FastMCP tool definitions backed by ``AssetLibraryClient``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from godot_store_mcp import config
from godot_store_mcp.download import stream_download
from godot_store_mcp.library.client import AssetLibraryClient, AssetLibraryError

ENV_USERNAME = "GODOT_ASSET_LIBRARY_USERNAME"
ENV_PASSWORD = "GODOT_ASSET_LIBRARY_PASSWORD"

_CREDENTIALS_REQUIRED_HINT = (
    "No credentials available and this MCP client can't prompt for them securely. "
    "To log in without exposing your password to the assistant, ask the user to run\n"
    "    godot-store-mcp login\n"
    "in their terminal — it prompts via getpass and saves the token locally. "
    f"Alternatively, set {ENV_USERNAME} and {ENV_PASSWORD} in the MCP server's "
    "environment and call this tool again, or save a token via library_set_token."
)


class _LibraryLoginInput(BaseModel):
    username: str = Field(description="Your godotengine.org/asset-library username.")
    # NOTE: MCP elicitation only permits string `format` values of
    # email/uri/date/date-time (per the restricted schema in the spec). A
    # `format: "password"` hint makes clients reject the whole elicitation
    # request, so we leave this as a plain string.
    password: str = Field(
        description=(
            "Your asset-library password. Entered directly in your MCP client's "
            "input form; it is never shared with the assistant."
        ),
    )


def _require_token() -> str:
    token = config.load().library.token
    if not token:
        raise RuntimeError(
            "Not logged in to the old asset library. Call library_login or library_set_token first."
        )
    return token


def _handle(err: AssetLibraryError) -> dict[str, Any]:
    return {"error": True, "status": err.status, "payload": err.payload}


def _resolve_credentials(
    username: str | None, password: str | None
) -> tuple[str | None, str | None]:
    return (
        username or os.environ.get(ENV_USERNAME) or None,
        password or os.environ.get(ENV_PASSWORD) or None,
    )


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="library_configure",
        description=(
            "Get configuration for the old asset library (godotengine.org/asset-library): "
            "category list and login URL. Use this to discover category IDs before searching."
        ),
    )
    async def library_configure(
        asset_type: Annotated[
            str | None,
            Field(description="Filter categories by 'any', 'addon', or 'project'."),
        ] = None,
    ) -> dict:
        async with AssetLibraryClient() as c:
            try:
                return await c.configure(asset_type=asset_type)
            except AssetLibraryError as e:
                return _handle(e)

    @mcp.tool(
        name="library_search",
        description=(
            "Search assets in the old Godot asset library. Returns paginated results. "
            "Most parameters mirror the documented REST API. Use library_configure to find "
            "category IDs."
        ),
    )
    async def library_search(
        query: Annotated[str | None, Field(description="Full-text search filter.")] = None,
        asset_type: Annotated[
            str | None, Field(description="'any', 'addon', or 'project'.")
        ] = None,
        category: Annotated[
            int | str | None, Field(description="Numeric category id from library_configure.")
        ] = None,
        support: Annotated[
            str | None,
            Field(
                description=(
                    "Support level filter. One or more of official|featured|community|testing, "
                    "joined with +."
                ),
            ),
        ] = None,
        user: Annotated[str | None, Field(description="Submitter username.")] = None,
        cost: Annotated[str | None, Field(description="License filter, e.g. MIT.")] = None,
        godot_version: Annotated[
            str | None,
            Field(
                description=(
                    "Godot version, e.g. '4.3' or '4.3.1'. If omitted, defaults to '4.6' — "
                    "the API otherwise legacy-defaults to 2.1, which hides nearly everything."
                ),
            ),
        ] = None,
        max_results: Annotated[
            int | None, Field(ge=1, le=500, description="Page size, 1-500.")
        ] = None,
        page: Annotated[int | None, Field(ge=0, description="Zero-indexed page.")] = None,
        sort: Annotated[
            str | None, Field(description="rating | cost | name | updated.")
        ] = None,
        reverse: Annotated[bool, Field(description="Reverse sort order.")] = False,
    ) -> dict:
        # The asset-library API has legacy defaults that surprise callers:
        # missing `type` → `addon` only; missing `godot_version` → `2.1` only.
        # Substitute sensible defaults so a bare search returns current assets.
        effective_type = asset_type or "any"
        effective_version = godot_version or "4.6"
        async with AssetLibraryClient() as c:
            try:
                return await c.search_assets(
                    asset_type=effective_type,
                    category=category,
                    support=support,
                    filter=query,
                    user=user,
                    cost=cost,
                    godot_version=effective_version,
                    max_results=max_results,
                    page=page,
                    sort=sort,
                    reverse=reverse,
                )
            except AssetLibraryError as e:
                return _handle(e)

    @mcp.tool(
        name="library_get_asset",
        description="Fetch full details for a single asset by numeric id (old asset library).",
    )
    async def library_get_asset(asset_id: int | str) -> dict:
        async with AssetLibraryClient() as c:
            try:
                return await c.get_asset(asset_id)
            except AssetLibraryError as e:
                return _handle(e)

    # ----------------------------------------------------------- auth tools

    @mcp.tool(
        name="library_login",
        description=(
            "Authenticate to the old asset library (godotengine.org/asset-library) "
            "and persist the returned token locally. Subsequent write tools (edits, "
            "delete, review) use this token automatically.\n\n"
            "PREFERRED: do NOT ask the user for their password. If your client "
            "supports interactive elicitation the tool prompts securely in-client. "
            "Otherwise instruct the user to run\n"
            "    godot-store-mcp login\n"
            "in their terminal — credentials are prompted via getpass and never "
            f"reach the assistant. Or set {ENV_USERNAME} and {ENV_PASSWORD} in the "
            "MCP server's environment and call this tool with no arguments. Passing "
            "username/password as tool arguments still works but exposes them to the "
            "LLM transcript — last resort only."
        ),
    )
    async def library_login(
        ctx: Context,
        username: Annotated[
            str | None,
            Field(
                description=(
                    f"Optional. Omit to read from {ENV_USERNAME}, to prompt in-client "
                    "(if supported), or to fall back to the CLI."
                ),
            ),
        ] = None,
        password: Annotated[
            str | None,
            Field(
                description=(
                    f"Optional. Omit to read from {ENV_PASSWORD}, to prompt in-client "
                    "(if supported), or to fall back to the CLI."
                ),
            ),
        ] = None,
    ) -> dict:
        resolved_user, resolved_pwd = _resolve_credentials(username, password)

        # No explicit args / env vars — try the client's secure prompt.
        if not (resolved_user and resolved_pwd):
            try:
                elicited = await ctx.elicit(
                    message="Sign in to the Godot asset library (godotengine.org/asset-library).",
                    schema=_LibraryLoginInput,
                )
            except Exception:  # client lacks elicitation support — fall through to hint
                elicited = None
            if elicited is not None:
                if elicited.action != "accept" or elicited.data is None:
                    return {
                        "error": True,
                        "kind": "cancelled",
                        "message": f"Login {elicited.action}; no credentials submitted.",
                    }
                resolved_user = elicited.data.username
                resolved_pwd = elicited.data.password

        if not (resolved_user and resolved_pwd):
            return {
                "error": True,
                "kind": "credentials_required",
                "message": _CREDENTIALS_REQUIRED_HINT,
            }

        async with AssetLibraryClient() as c:
            try:
                result = await c.login(resolved_user, resolved_pwd)
            except AssetLibraryError as e:
                return _handle(e)
        token = result.get("token")
        if not token:
            return {"error": True, "payload": result}
        creds = config.load()
        creds.library.username = result.get("username") or resolved_user
        creds.library.token = token
        path = config.save(creds)
        return {
            "authenticated": True,
            "username": creds.library.username,
            "credentials_path": str(path),
        }

    @mcp.tool(
        name="library_set_token",
        description=(
            "Manually persist an asset-library token (obtained out of band). "
            "Useful for testing or if you already have a token."
        ),
    )
    async def library_set_token(
        token: str,
        username: Annotated[str | None, Field(description="Optional username label.")] = None,
    ) -> dict:
        creds = config.load()
        creds.library.token = token
        if username is not None:
            creds.library.username = username
        path = config.save(creds)
        return {"saved": True, "credentials_path": str(path)}

    @mcp.tool(
        name="library_logout",
        description="Log out (invalidates token server-side) and clear the local token.",
    )
    async def library_logout() -> dict:
        creds = config.load()
        token = creds.library.token
        if not token:
            return {"already_logged_out": True}
        async with AssetLibraryClient() as c:
            try:
                result = await c.logout(token)
            except AssetLibraryError as e:
                # Even if remote fails, clear local.
                config.clear_library()
                return {"local_cleared": True, "remote_error": _handle(e)}
        config.clear_library()
        return {"authenticated": False, "remote": result}

    @mcp.tool(
        name="library_register",
        description="Register a new account on the old asset library.",
    )
    async def library_register(username: str, password: str, email: str) -> dict:
        async with AssetLibraryClient() as c:
            try:
                return await c.register(username, password, email)
            except AssetLibraryError as e:
                return _handle(e)

    @mcp.tool(
        name="library_change_password",
        description=(
            "Change the password for the currently logged-in asset-library account. "
            "Invalidates the local token; you must log in again afterwards."
        ),
    )
    async def library_change_password(old_password: str, new_password: str) -> dict:
        token = _require_token()
        async with AssetLibraryClient() as c:
            try:
                result = await c.change_password(token, old_password, new_password)
            except AssetLibraryError as e:
                return _handle(e)
        config.clear_library()
        return {"changed": True, "local_cleared": True, "remote": result}

    # -------------------------------------------------------------- writes

    @mcp.tool(
        name="library_submit_edit",
        description=(
            "Create a new asset, edit an existing asset, or update a pending edit. "
            "Pass `asset_id` to edit an existing asset, `edit_id` to update a pending edit, "
            "or neither to create a new asset. `fields` is a dict of asset fields (title, "
            "description, category_id, godot_version, version_string, cost, download_provider, "
            "download_commit, browse_url, issues_url, icon_url, download_url, previews)."
        ),
    )
    async def library_submit_edit(
        fields: dict[str, Any],
        asset_id: Annotated[
            int | str | None, Field(description="Existing asset id to edit.")
        ] = None,
        edit_id: Annotated[
            int | str | None, Field(description="Existing pending edit id to update.")
        ] = None,
    ) -> dict:
        token = _require_token()
        async with AssetLibraryClient() as c:
            try:
                return await c.submit_edit(
                    token=token, asset_id=asset_id, edit_id=edit_id, fields=fields
                )
            except AssetLibraryError as e:
                return _handle(e)

    @mcp.tool(
        name="library_get_edit",
        description="Fetch a previously-submitted asset edit by id.",
    )
    async def library_get_edit(edit_id: int | str) -> dict:
        async with AssetLibraryClient() as c:
            try:
                return await c.get_edit(edit_id)
            except AssetLibraryError as e:
                return _handle(e)

    @mcp.tool(
        name="library_request_review",
        description="Submit a pending edit for moderator review.",
    )
    async def library_request_review(edit_id: int | str) -> dict:
        token = _require_token()
        async with AssetLibraryClient() as c:
            try:
                return await c.request_review(edit_id, token)
            except AssetLibraryError as e:
                return _handle(e)

    @mcp.tool(
        name="library_delete_asset",
        description="Soft-delete one of your assets (or any asset if you're a moderator).",
    )
    async def library_delete_asset(asset_id: int | str) -> dict:
        token = _require_token()
        async with AssetLibraryClient() as c:
            try:
                return await c.delete_asset(asset_id, token)
            except AssetLibraryError as e:
                return _handle(e)

    @mcp.tool(
        name="library_undelete_asset",
        description="Revert a soft-deletion on one of your assets.",
    )
    async def library_undelete_asset(asset_id: int | str) -> dict:
        token = _require_token()
        async with AssetLibraryClient() as c:
            try:
                return await c.undelete_asset(asset_id, token)
            except AssetLibraryError as e:
                return _handle(e)

    @mcp.tool(
        name="library_set_support_level",
        description=(
            "Moderator-only: change an asset's support level "
            "(official | featured | community | testing)."
        ),
    )
    async def library_set_support_level(asset_id: int | str, support_level: str) -> dict:
        token = _require_token()
        async with AssetLibraryClient() as c:
            try:
                return await c.set_support_level(asset_id, support_level, token)
            except AssetLibraryError as e:
                return _handle(e)

    # ----------------------------------------------------------- downloads

    @mcp.tool(
        name="library_download_asset",
        description=(
            "Download an asset's zip to a local directory. Uses the asset's download_url "
            "(typically a GitHub archive). Optionally verifies a sha256 hash."
        ),
    )
    async def library_download_asset(
        asset_id: int | str,
        dest_dir: Annotated[
            str, Field(description="Destination directory; created if missing.")
        ],
        filename: Annotated[
            str | None, Field(description="Override filename; default uses URL/headers.")
        ] = None,
        verify_sha256: Annotated[
            bool,
            Field(
                description=(
                    "If true and the asset has a non-empty download_hash, verify it after download."
                ),
            ),
        ] = True,
    ) -> dict:
        async with AssetLibraryClient() as c:
            try:
                asset = await c.get_asset(asset_id)
            except AssetLibraryError as e:
                return _handle(e)
        url = asset.get("download_url")
        if not url:
            return {"error": True, "message": "asset has no download_url", "asset": asset}
        expected = asset.get("download_hash") if verify_sha256 else None
        if expected == "":
            expected = None
        result = await stream_download(
            url, Path(dest_dir), filename=filename, expected_sha256=expected
        )
        return {
            "asset_id": asset.get("asset_id"),
            "title": asset.get("title"),
            "version_string": asset.get("version_string"),
            **result,
        }
