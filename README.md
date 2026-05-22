# godot-asset-store-mcp

An [MCP](https://modelcontextprotocol.io) server that lets Claude (or any MCP
client) authenticate against, browse, manage, and download assets from both
Godot asset marketplaces:

* **Old asset library** — <https://godotengine.org/asset-library/> — uses the
  documented [REST API](https://github.com/godotengine/godot-asset-library/blob/master/API.md).
* **New asset store** (beta) — <https://store.godotengine.org/> — Keycloak SSO
  + HTMX server-rendered HTML. Tools here scrape the live site, so they may
  break as the beta evolves.

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/jakecattrall/godot-asset-store-mcp.git
cd godot-asset-store-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Optional: only needed for the browser-fallback login tool
# (used if Keycloak ever demands reCAPTCHA / 2FA / a required action):
pip install -e '.[browser]'
python -m playwright install chromium
```

## Run

The server speaks MCP over stdio:

```bash
godot-asset-store-mcp
```

### Claude Desktop / Claude Code

Add this to your MCP client config (replace the path with where you cloned the repo):

```json
{
  "mcpServers": {
    "godot-asset-store": {
      "command": "/absolute/path/to/godot-asset-store-mcp/.venv/bin/godot-asset-store-mcp"
    }
  }
}
```

## Credential storage

Tokens and the new-store session cookie are written to
`~/.config/godot-asset-store-mcp/credentials.json` (chmod 600).
Override the location with `GODOT_ASSET_STORE_MCP_CONFIG=/path/to/file.json`.

## Tools

### Old asset library (`library_*`)

| Tool | What it does |
| --- | --- |
| `library_configure` | List categories and login URL. |
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
| `store_search` | Free-text search (use `#tag` to search a tag). Supports pagination via `scroll`. |
| `store_get_asset` | Fetch one asset by publisher slug + asset slug, including all download versions. |
| `store_list_publisher_assets` | List every asset by a given publisher. |
| `store_login` | Sign in with username + password via the Keycloak OIDC flow (no browser). |
| `store_login_browser` | Fallback: open a Chromium window for SSO. Use if `store_login` returns `interactive_required` (captcha / 2FA). Needs the `[browser]` extra. |
| `store_set_session_cookie` | Paste a `session` cookie value if neither login flow is viable. |
| `store_logout` | Clear the stored session cookie. |
| `store_add_to_library` / `store_remove_from_library` | Library management on the new store. |
| `store_download_asset` | Stream a specific version's zip from the CDN (or in-store endpoint). |

## Beta caveats (new store)

* The new store has no public JSON API yet. Tool implementations parse HTML,
  so selector or URL changes upstream will break things until the parser is
  updated.
* Login uses Keycloak OIDC. The default `store_login` tool does the whole
  Authorization-Code flow in pure `httpx` with no browser. If Keycloak ever
  enables reCAPTCHA, 2FA, or another required action, `store_login` returns
  `interactive_required`; fall back to `store_login_browser` (Playwright)
  or paste a cookie via `store_set_session_cookie`.
* Asset URLs use slug pairs: `https://store.godotengine.org/asset/{publisher}/{slug}/`.

## License

MIT — see `LICENSE`.
