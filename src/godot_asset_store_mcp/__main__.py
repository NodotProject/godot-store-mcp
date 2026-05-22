"""CLI entry point — runs the FastMCP server over stdio."""

from godot_asset_store_mcp.server import mcp


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
