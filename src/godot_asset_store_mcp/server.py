"""FastMCP server wiring.

Tools are registered in two groups:
* ``library_*`` — old asset library (``godotengine.org/asset-library``).
* ``store_*``   — new asset store (``store.godotengine.org``), beta.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from godot_asset_store_mcp.library import tools as library_tools
from godot_asset_store_mcp.store import tools as store_tools

mcp = FastMCP(
    name="godot-asset-store",
    instructions=(
        "Browse, authenticate against, and download from the Godot asset library "
        "(godotengine.org/asset-library) and the new Godot Asset Store "
        "(store.godotengine.org). Tools prefixed `library_` target the documented "
        "REST API; tools prefixed `store_` scrape the beta HTMX site and may be less "
        "stable. Use `*_login` to authenticate before calling write tools."
    ),
)

library_tools.register(mcp)
store_tools.register(mcp)


__all__ = ["mcp"]
