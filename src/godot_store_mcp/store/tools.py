"""FastMCP tools backed by ``AssetStoreClient``.

Most tools here scrape HTML — selectors may break as the beta store evolves.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urljoin

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from godot_store_mcp import config
from godot_store_mcp.download import stream_download
from godot_store_mcp.store.client import AssetStoreClient, StoreError

ENV_USERNAME = "GODOT_ASSET_STORE_USERNAME"
ENV_PASSWORD = "GODOT_ASSET_STORE_PASSWORD"

_CREDENTIALS_REQUIRED_HINT = (
    "No credentials available and this MCP client can't prompt for them securely. "
    "To log in without exposing your password to the assistant, ask the user to run\n"
    "    godot-store-mcp login-store\n"
    "in their terminal — it prompts via getpass and saves the session cookie locally. "
    f"Alternatively, set {ENV_USERNAME} and {ENV_PASSWORD} in the MCP server's "
    "environment and call this tool again, or paste a cookie via "
    "store_set_session_cookie."
)


class _StoreLoginInput(BaseModel):
    username: str = Field(description="Your store.godotengine.org username or email.")
    # NOTE: MCP elicitation only permits string `format` values of
    # email/uri/date/date-time (per the restricted schema in the spec). A
    # `format: "password"` hint makes clients reject the whole elicitation
    # request, so we leave this as a plain string.
    password: str = Field(
        description=(
            "Your store password. Entered directly in your MCP client's input form; "
            "it is never shared with the assistant."
        ),
    )


def _handle(err: StoreError) -> dict[str, Any]:
    return {"error": True, "status": err.status, "message": str(err)}


def _resolve_credentials(
    username: str | None, password: str | None
) -> tuple[str | None, str | None]:
    return (
        username or os.environ.get(ENV_USERNAME) or None,
        password or os.environ.get(ENV_PASSWORD) or None,
    )


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

    @mcp.tool(
        name="store_list_my_uploads",
        description=(
            "List the signed-in user's own assets (including unpublished "
            "drafts) from the authenticated /my_uploads/ page. Requires login. "
            "Use this — not store_list_publisher_assets — to find assets you "
            "manage; the public publisher page omits drafts."
        ),
    )
    async def store_list_my_uploads() -> dict:
        async with _client_from_creds() as c:
            try:
                return await c.list_my_uploads()
            except StoreError as e:
                return _handle(e)

    # ---------------------------------------------------------------- auth

    @mcp.tool(
        name="store_login",
        description=(
            "Sign in to store.godotengine.org by driving the Keycloak OIDC flow. "
            "No browser required. If Keycloak demands reCAPTCHA, 2FA, or another "
            "interactive step, the tool returns an error pointing to "
            "`store_login_browser`.\n\n"
            "PREFERRED: do NOT ask the user for their password. If your client "
            "supports interactive elicitation the tool prompts securely in-client. "
            "Otherwise instruct the user to run\n"
            "    godot-store-mcp login-store\n"
            "in their terminal — credentials are prompted via getpass and never "
            f"reach the assistant. Or set {ENV_USERNAME} and {ENV_PASSWORD} in the "
            "MCP server's environment and call this tool with no arguments. Passing "
            "username/password as tool arguments still works but exposes them to the "
            "LLM transcript — last resort only."
        ),
    )
    async def store_login(
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
        from godot_store_mcp.store.oidc import (
            InteractiveAuthRequired,
            InvalidCredentials,
            LoginError,
            scripted_login,
        )

        resolved_user, resolved_pwd = _resolve_credentials(username, password)

        # No explicit args / env vars — try the client's secure prompt.
        if not (resolved_user and resolved_pwd):
            try:
                elicited = await ctx.elicit(
                    message="Sign in to the new Godot Asset Store (store.godotengine.org).",
                    schema=_StoreLoginInput,
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

        try:
            return await scripted_login(resolved_user, resolved_pwd)
        except InvalidCredentials as e:
            return {"error": True, "kind": "invalid_credentials", "message": str(e)}
        except InteractiveAuthRequired as e:
            return {"error": True, "kind": "interactive_required", "message": str(e)}
        except LoginError as e:
            return {"error": True, "kind": "login_error", "message": str(e)}

    @mcp.tool(
        name="store_login_browser",
        description=(
            "Fallback login: open a Chromium window so the user can sign in to "
            "store.godotengine.org manually (handles captcha, 2FA, password resets, "
            "etc.). The tool then captures the session cookie from the browser and "
            "stores it locally. Requires the optional `browser` extra: "
            "`pip install 'godot-store-mcp[browser]'` and a one-time "
            "`python -m playwright install chromium`."
        ),
    )
    async def store_login_browser(
        timeout_seconds: Annotated[
            int,
            Field(
                ge=30,
                le=1800,
                description="How long to wait for the user to finish logging in (seconds).",
            ),
        ] = 600,
    ) -> dict:
        from godot_store_mcp.store.login import interactive_login

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
        name="store_create_asset",
        description=(
            "Create a new asset stub on the new store (requires login). Submits "
            "the /asset/new/ form: publisher + name + url_slug + terms. The store "
            "creates a draft listing and redirects to its edit page. Description, "
            "screenshots, versions, and download archives must still be filled in "
            "via the web UI afterwards. Returns the new asset's URL on success."
        ),
    )
    async def store_create_asset(
        name: Annotated[str, Field(description="Public asset title.")],
        url_slug: Annotated[
            str,
            Field(description="URL slug (the path segment after the publisher in /asset/<pub>/<slug>/)."),
        ],
        publisher_id: Annotated[
            str | None,
            Field(
                description=(
                    "Numeric publisher id from the /asset/new/ form. Omit if you "
                    "only have one publisher; the tool picks it automatically."
                ),
            ),
        ] = None,
    ) -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.create_asset(
                    name=name, url_slug=url_slug, publisher_id=publisher_id
                )
            except StoreError as e:
                return _handle(e)

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

    # ----------------------------------------------------------- manage tab

    @mcp.tool(
        name="store_suggest_tags",
        description=(
            "Query the store's tag autocomplete (/possible-tags/?q=) and return matching "
            "tags as a list of {display_name, slug} entries. Useful for finding the canonical "
            "slug to pass to store_edit_asset. Note: the store currently truncates both "
            "display_name and slug at ~18 characters, so longer queries may come back trimmed."
        ),
    )
    async def store_suggest_tags(
        query: Annotated[str, Field(description="Free-text tag query.")],
    ) -> dict:
        async with _client_from_creds() as c:
            try:
                return {"query": query, "results": await c.suggest_tags(query)}
            except StoreError as e:
                return _handle(e)

    @mcp.tool(
        name="store_edit_asset",
        description=(
            "Patch the Settings tab of an asset you own. Any argument left as null/None "
            "preserves the asset's current value (the tool re-reads the manage page to "
            "fill in unchanged fields). To replace the tag set, pass `tags` as a list; "
            "leave it None to keep the current tags. `type_` accepts 'addon' or 'project'. "
            "Requires login."
        ),
    )
    async def store_edit_asset(
        publisher: str,
        slug: str,
        name: str | None = None,
        description: Annotated[
            str | None, Field(description="Short blurb (one or two sentences).")
        ] = None,
        body: Annotated[
            str | None,
            Field(description="Long description (markdown). Posted as `body_raw`."),
        ] = None,
        tags: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Replace the current tag list. Pass display names or slugs; "
                    "the tool resolves each via /possible-tags/?q="
                ),
            ),
        ] = None,
        type_: Annotated[
            str | None, Field(description="'addon' or 'project' (or the raw '0'/'1').")
        ] = None,
        license_predefined: Annotated[
            str | None,
            Field(
                description=(
                    "License URL from the dropdown (e.g. "
                    "'https://choosealicense.com/licenses/mit/'), or 'OTHER' to use "
                    "the custom license_type/license_url fields."
                ),
            ),
        ] = None,
        license_type: str | None = None,
        license_url: str | None = None,
        source: Annotated[
            str | None, Field(description="Public source URL (e.g. GitHub repo).")
        ] = None,
        uses_ai: bool | None = None,
        uses_ai_reason: str | None = None,
    ) -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.edit_settings(
                    publisher,
                    slug,
                    name=name,
                    description=description,
                    body=body,
                    tags=tags,
                    type_=type_,
                    license_predefined=license_predefined,
                    license_type=license_type,
                    license_url=license_url,
                    source=source,
                    uses_ai=uses_ai,
                    uses_ai_reason=uses_ai_reason,
                )
            except StoreError as e:
                return _handle(e)

    @mcp.tool(
        name="store_update_media",
        description=(
            "Update the Media tab: upload a thumbnail and/or featured image, set the "
            "YouTube video URL, and append screenshots. All file arguments are LOCAL "
            "filesystem paths — fetch a remote image first (e.g. with `curl`) and pass "
            "the resulting path. Existing screenshots are preserved by default. "
            "Requires login."
        ),
    )
    async def store_update_media(
        publisher: str,
        slug: str,
        thumbnail_path: Annotated[
            str | None,
            Field(description="Local path to a thumbnail image. None = leave unchanged."),
        ] = None,
        featured_thumbnail_path: Annotated[
            str | None,
            Field(description="Local path to a wide/featured image. None = leave unchanged."),
        ] = None,
        clear_featured: Annotated[
            bool, Field(description="Set true to remove the current featured image.")
        ] = False,
        video_url: Annotated[
            str | None,
            Field(description="YouTube URL, or '' to clear. None = leave unchanged."),
        ] = None,
        add_screenshots: Annotated[
            list[str] | None,
            Field(description="Local image paths to append to the screenshot gallery."),
        ] = None,
        keep_existing_screenshots: bool = True,
    ) -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.update_media(
                    publisher,
                    slug,
                    thumbnail_path=thumbnail_path,
                    featured_thumbnail_path=featured_thumbnail_path,
                    clear_featured=clear_featured,
                    video_url=video_url,
                    add_screenshots=add_screenshots,
                    keep_existing_screenshots=keep_existing_screenshots,
                )
            except StoreError as e:
                return _handle(e)

    @mcp.tool(
        name="store_upload_version",
        description=(
            "Upload a new version archive (zip). Performs the three-step flow used by "
            "the manage page: request a pre-signed S3 URL, PUT the file directly to S3, "
            "then POST /version/create/ to commit. `file_path` must be a local zip; "
            "fetch the GitHub archive first if necessary. Requires login."
        ),
    )
    async def store_upload_version(
        publisher: str,
        slug: str,
        file_path: Annotated[str, Field(description="Local path to the version zip.")],
        version_name: Annotated[
            str, Field(description="Version string shown to users, e.g. '0.1.9' or 'v0.3.3'.")
        ],
        changelog: str = "",
        stable: bool = True,
        min_godot_version: Annotated[
            str,
            Field(
                description=(
                    "Exact select option value, e.g. 'Godot 4.4' or 'Undefined'. "
                    "Note: must be the full label (including 'Godot ' prefix)."
                ),
            ),
        ] = "Undefined",
        max_godot_version: str = "Undefined",
        version_notes: str = "",
    ) -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.upload_version(
                    publisher,
                    slug,
                    file_path=file_path,
                    version_name=version_name,
                    changelog=changelog,
                    stable=stable,
                    min_godot_version=min_godot_version,
                    max_godot_version=max_godot_version,
                    version_notes=version_notes,
                )
            except StoreError as e:
                return _handle(e)

    @mcp.tool(
        name="store_get_pricing",
        description=(
            "Read the Pricing tab values (price_cent, reviews_disabled, donation_text, "
            "donation_url) from the manage page. Requires login (must be able to manage "
            "the asset)."
        ),
    )
    async def store_get_pricing(publisher: str, slug: str) -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.get_pricing(publisher, slug)
            except StoreError as e:
                return _handle(e)

    @mcp.tool(
        name="store_set_pricing",
        description=(
            "Update the Pricing tab (price in cents, reviews-disabled toggle, donation "
            "fields). Pass None to leave a field unchanged. Requires login."
        ),
    )
    async def store_set_pricing(
        publisher: str,
        slug: str,
        price_cent: Annotated[
            int | None,
            Field(description="Price in cents (0 = free). None to leave unchanged."),
        ] = None,
        reviews_disabled: bool | None = None,
        donation_text: str | None = None,
        donation_url: str | None = None,
    ) -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.set_pricing(
                    publisher,
                    slug,
                    price_cent=price_cent,
                    reviews_disabled=reviews_disabled,
                    donation_text=donation_text,
                    donation_url=donation_url,
                )
            except StoreError as e:
                return _handle(e)

    @mcp.tool(
        name="store_submit_for_review",
        description=(
            "Submit the asset to moderators for review (equivalent to clicking the "
            "Publish button on the manage page). Once approved by a moderator the asset "
            "becomes publicly visible. Requires login."
        ),
    )
    async def store_submit_for_review(publisher: str, slug: str) -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.submit_for_review(publisher, slug)
            except StoreError as e:
                return _handle(e)

    # ------------------------------------------------------------- tickets

    @mcp.tool(
        name="store_list_tickets",
        description=(
            "List the support tickets visible to the logged-in user on the new store "
            "(/tickets/). Returns separate `user_tickets` (own + publisher tickets) and "
            "`moderation_tickets` (only populated for moderators). Each entry includes "
            "id, url, title, sender username, status ('open' or 'closed') and the section "
            "heading it appeared under. Requires login."
        ),
    )
    async def store_list_tickets() -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.list_tickets()
            except StoreError as e:
                return _handle(e)

    @mcp.tool(
        name="store_get_ticket",
        description=(
            "Fetch the detail page for a single support ticket by numeric id. Returns "
            "title, creation timestamp, related asset (if any), status, and the full "
            "message thread (sender, timestamp, text). Requires login."
        ),
    )
    async def store_get_ticket(
        ticket_id: Annotated[
            int, Field(description="Numeric ticket id (the N in /ticket/N/).")
        ],
    ) -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.get_ticket(ticket_id)
            except StoreError as e:
                return _handle(e)

    @mcp.tool(
        name="store_create_ticket",
        description=(
            "Open a new support ticket on the new store (the 'Submit request' form at "
            "/tickets/#new-ticket). Requires login. This is the generic support flow — "
            "asset-specific 'Regarding asset: ...' tickets are created by moderators "
            "from their moderation queue, not by users via this form."
        ),
    )
    async def store_create_ticket(
        title: Annotated[str, Field(description="Ticket title / subject line.")],
        message: Annotated[str, Field(description="Body of the ticket.")],
    ) -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.create_ticket(title=title, message=message)
            except StoreError as e:
                return _handle(e)

    @mcp.tool(
        name="store_reply_ticket",
        description=(
            "Post a reply on an open support ticket. Closed tickets reject replies — "
            "reopen first via store_reopen_ticket. Requires login."
        ),
    )
    async def store_reply_ticket(
        ticket_id: Annotated[int, Field(description="Numeric ticket id.")],
        message: Annotated[str, Field(description="Reply body.")],
    ) -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.reply_ticket(ticket_id, message)
            except StoreError as e:
                return _handle(e)

    @mcp.tool(
        name="store_close_ticket",
        description=(
            "Close an open support ticket. The store rejects closing an already-closed "
            "ticket. Requires login."
        ),
    )
    async def store_close_ticket(
        ticket_id: Annotated[int, Field(description="Numeric ticket id.")],
    ) -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.set_ticket_status(ticket_id, "close")
            except StoreError as e:
                return _handle(e)

    @mcp.tool(
        name="store_reopen_ticket",
        description=(
            "Reopen a previously-closed support ticket so replies can be posted again. "
            "Requires login."
        ),
    )
    async def store_reopen_ticket(
        ticket_id: Annotated[int, Field(description="Numeric ticket id.")],
    ) -> dict:
        cookie = config.load().store.session_cookie
        if not cookie:
            return {"error": True, "message": "Not logged in. Call store_login first."}
        async with AssetStoreClient(session_cookie=cookie) as c:
            try:
                return await c.set_ticket_status(ticket_id, "reopen")
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
