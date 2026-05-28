"""Entry point — dispatches to stdio (default) or streamable-HTTP transport.

Usage (stdio, for local MCP clients like Claude Desktop / Claude Code):
    mcp-agentic-patterns

Usage (HTTP):
    mcp-agentic-patterns http --host 0.0.0.0 --port 8080

Catalog data source (priority order — see catalog.resolve_catalog_dir for full
detail):
    --catalog-dir <path>     explicit argument
    CATALOG_DIR=<path>       environment variable
    ../agent-patterns-catalog/   sibling repo (dev convenience)
    ~/.cache/mcp-agentic-patterns/patterns-main/   on-disk cache (populated below)
    fresh fetch of github.com/agentpatternscatalog/patterns (one-time, cached)
    <bundled package data>   shipped with PyPI wheel

Force a re-fetch of the catalog from GitHub:
    --refresh-catalog          flag
    MCP_CATALOG_REFRESH=1      environment variable
"""

from __future__ import annotations

import argparse
import sys

from .server import build_server


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="mcp-agentic-patterns",
        description="MCP server for the Agentic Patterns Catalog.",
    )
    parser.add_argument(
        "transport",
        nargs="?",
        default="stdio",
        choices=["stdio", "http"],
        help="MCP transport (default: stdio).",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind host (transport=http).")
    parser.add_argument("--port", default=8080, type=int, help="HTTP bind port (transport=http).")
    parser.add_argument(
        "--catalog-dir",
        default=None,
        help="Path to the agentic patterns catalog repo (overrides CATALOG_DIR env).",
    )
    parser.add_argument(
        "--refresh-catalog",
        action="store_true",
        help=(
            "Re-fetch the catalog from github.com/agentpatternscatalog/patterns "
            "and overwrite the local cache."
        ),
    )
    args = parser.parse_args()

    mcp = build_server(
        catalog_dir=args.catalog_dir,
        host=args.host,
        port=args.port,
        refresh=args.refresh_catalog,
    )
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    sys.exit(main())
