# godot-store-mcp

An [MCP](https://modelcontextprotocol.io) server that lets Claude — or any
MCP-aware client — search, manage, publish to, and download from both Godot
asset marketplaces:

- **Old asset library** — <https://godotengine.org/asset-library/> — uses the
  documented [REST API](https://github.com/godotengine/godot-asset-library/blob/master/API.md).
- **New asset store** (beta) — <https://store.godotengine.org/> — Keycloak SSO
  + HTMX server-rendered HTML. Tools here scrape the live site, so they may
  break as the beta evolves.

> [!WARNING]
> The new asset store is in beta and has no public JSON API yet. `store_*`
> tools parse HTML — selector or URL changes upstream will break things until
> the parser is updated. File an issue if you hit a break.

## Features

- Search both marketplaces with sensible defaults (e.g. Godot 4.6 instead of
  the legacy 2.1 default the old API uses).
- Authenticate by calling the login tool with no arguments: if your MCP client
  supports [MCP elicitation] it prompts you for username and password, so they
  are typed by you and never reach the LLM transcript. Clients without
  elicitation (e.g. Claude Code) can authenticate out of band via the
  `godot-store-mcp login` / `login-store` CLI subcommands or environment
  variables — see [Authentication](#authentication).
- Publish workflow on the new store: create a draft, edit settings, upload
  thumbnails/screenshots, upload version zips, set pricing, submit for review.
- Stream downloads with optional sha256 verification.
- Pure-`httpx` Keycloak OIDC flow — no browser required for the common case.
  Falls back to a Playwright-driven Chromium window if Keycloak ever demands
  reCAPTCHA, 2FA, or a required action.

## Requirements

- Python 3.11+
- A POSIX or Windows shell. Tested on Linux.

## Install

```bash
git clone https://github.com/NodotProject/godot-store-mcp.git
cd godot-store-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Optional browser-fallback login (only needed if `store_login` returns
`interactive_required`):

```bash
pip install -e '.[browser]'
python -m playwright install chromium
```

## Configure your MCP client

The server speaks MCP over stdio. Point your client at the installed entry
point:

```json
{
  "mcpServers": {
    "godot-store": {
      "command": "/absolute/path/to/godot-store-mcp/.venv/bin/godot-store-mcp"
    }
  }
}
```

For Claude Desktop the config lives at:

- macOS — `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux — `~/.config/Claude/claude_desktop_config.json`
- Windows — `%APPDATA%\Claude\claude_desktop_config.json`

## Authentication

Both marketplaces are read-only for browsing — auth is only needed for write
actions (publishing, downloading paid assets, library management).

Credentials are saved to `~/.config/godot-store-mcp/credentials.json`
(chmod 600). Override the location with `GODOT_STORE_MCP_CONFIG=/path/to/file.json`.

Pick whichever path your MCP client supports, in order of preference:

**1. In-client secure prompt (clients with elicitation support).** Call
`library_login` (old library) or `store_login` (new store) with no arguments.
Your client prompts you for username and password through its secure input form
via [MCP elicitation], so they are typed by you and never pass through the
assistant or the LLM transcript.

**2. Out-of-band CLI (recommended for clients without elicitation, e.g. Claude
Code).** Run the login subcommand in your own terminal — it prompts via
`getpass` and saves the token / session cookie locally; the LLM never sees your
password:

```bash
godot-store-mcp login         # old asset library (godotengine.org/asset-library)
godot-store-mcp login-store   # new asset store (store.godotengine.org, OIDC)
```

**3. Environment variables.** Set these in the MCP server's environment, then
call `library_login` / `store_login` with no arguments:

```bash
GODOT_ASSET_LIBRARY_USERNAME / GODOT_ASSET_LIBRARY_PASSWORD   # old library
GODOT_ASSET_STORE_USERNAME   / GODOT_ASSET_STORE_PASSWORD     # new store
```

**4. Other fallbacks.**

- New store: `store_login_browser` opens a Chromium window to sign in (also
  handles reCAPTCHA / 2FA / password resets), or paste an existing `session`
  cookie via `store_set_session_cookie`.
- Old library: obtain a token out of band and save it with `library_set_token`.

> Passing `username`/`password` directly as tool arguments works too, but they
> land in the LLM transcript — use only as a last resort.

[MCP elicitation]: https://modelcontextprotocol.io/specification/draft/client/elicitation

## Tools

### Old asset library (`library_*`)

| Tool | What it does |
| --- | --- |
| `library_configure` | List categories and the login URL. |
| `library_search` | Search assets by text/category/support/user/version. |
| `library_get_asset` | Fetch full details for one asset. |
| `library_login` / `library_logout` / `library_register` | Auth flows. Token is persisted automatically. |
| `library_set_token` | Manually save a token. |
| `library_change_password` | Change password (requires login; invalidates token). |
| `library_submit_edit` | Create a new asset, edit one, or update a pending edit. |
| `library_get_edit` | Fetch a pending edit. |
| `library_request_review` | Submit a pending edit for moderator review. |
| `library_delete_asset` / `library_undelete_asset` | Soft-delete or restore one of your assets. |
| `library_set_support_level` | Moderator-only: change support level. |
| `library_download_asset` | Stream the asset zip to disk, optionally verifying sha256. |

### New asset store (`store_*`, beta)

| Tool | What it does |
| --- | --- |
| `store_search` | Free-text search (use `#tag` to search a tag). Paginates via `scroll`. |
| `store_get_asset` | Fetch one asset by publisher slug + asset slug, including all download versions. |
| `store_list_publisher_assets` | List every asset by a given publisher. |
| `store_login` | Sign in with username + password via the Keycloak OIDC flow (no browser). |
| `store_login_browser` | Fallback: open a Chromium window for SSO. Use if `store_login` returns `interactive_required`. Needs the `[browser]` extra. |
| `store_set_session_cookie` | Paste a `session` cookie value if neither login flow is viable. |
| `store_logout` | Clear the stored session cookie. |
| `store_create_asset` | Create a new draft asset (publisher + name + slug + terms). |
| `store_edit_asset` | Patch the Settings tab (name, description, body, tags, license, source, AI flag). |
| `store_update_media` | Upload thumbnail / featured image / screenshots, set video URL. |
| `store_upload_version` | Upload a new version zip via the pre-signed-S3 + commit flow. |
| `store_get_pricing` / `store_set_pricing` | Read and write the Pricing tab. |
| `store_suggest_tags` | Query the tag autocomplete to find canonical slugs. |
| `store_submit_for_review` | Submit a draft to moderators (equivalent to clicking Publish). |
| `store_add_to_library` / `store_remove_from_library` | Library management on the new store. |
| `store_list_tickets` | List support tickets visible to you (own + publisher; mod queue if you're a mod). |
| `store_get_ticket` | Fetch one ticket's message thread by numeric id. |
| `store_create_ticket` | Open a generic support ticket (the "Submit request" form). |
| `store_reply_ticket` | Post a reply on an open ticket. |
| `store_close_ticket` / `store_reopen_ticket` | Toggle a ticket's status. |
| `store_download_asset` | Stream a specific version's zip from the CDN (or the in-store endpoint). |

## Beta caveats (new store)

- The new store has no public JSON API yet. Tool implementations parse HTML,
  so selector or URL changes upstream will break things until the parser is
  updated.
- Login uses Keycloak OIDC. The default `store_login` tool does the whole
  Authorization-Code flow in pure `httpx` with no browser. If Keycloak ever
  enables reCAPTCHA, 2FA, or another required action, `store_login` returns
  `interactive_required`; fall back to `store_login_browser` (Playwright) or
  paste a cookie via `store_set_session_cookie`.
- Asset URLs use slug pairs: `https://store.godotengine.org/asset/{publisher}/{slug}/`.

## Development

```bash
pip install -e .
pip install ruff
ruff check .
```

Run the server directly for local debugging:

```bash
godot-store-mcp        # MCP over stdio
```

## Contributing

Issues and pull requests are welcome at
<https://github.com/NodotProject/godot-store-mcp>. When reporting a scraping
break, please include the asset/publisher slug or search query that triggered
it — that's usually enough to reproduce.

## License

MIT — see [LICENSE](LICENSE).
