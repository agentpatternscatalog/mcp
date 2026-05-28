"""Smoke tests — load the catalog, build the server, exercise tools end-to-end.

Run with the sibling catalog repo as data source:
    CATALOG_DIR=../../agent-patterns-catalog python -m pytest mcp/tests
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp_agentic_patterns.catalog import load_catalog  # noqa: E402
from mcp_agentic_patterns.server import build_server  # noqa: E402


def _catalog():
    catalog_dir = os.environ.get("CATALOG_DIR")
    if not catalog_dir:
        sibling = Path(__file__).resolve().parents[2] / "agent-patterns-catalog"
        if (sibling / "patterns-src").is_dir():
            catalog_dir = str(sibling)
    return load_catalog(catalog_dir)


def _call(server, tool: str, **args):
    """Invoke an MCP tool through the server. FastMCP returns a tuple
    (content_blocks, structured_content); we use the structured side."""
    result = asyncio.run(server.call_tool(tool, args))
    if isinstance(result, tuple) and len(result) == 2 and result[1] is not None:
        structured = result[1]
        # structured_content can be {"result": <value>} for list/scalar returns.
        return structured.get("result", structured) if isinstance(structured, dict) else structured
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def test_catalog_loads():
    cat = _catalog()
    assert len(cat.patterns) > 100, f"too few patterns: {len(cat.patterns)}"
    assert len(cat.compositions) > 50, f"too few compositions: {len(cat.compositions)}"
    assert len(cat.methodologies) > 10, f"too few methodologies: {len(cat.methodologies)}"


def test_reverse_index_populated():
    cat = _catalog()
    impl = cat.frameworks_implementing.get("tool-use", [])
    assert len(impl) >= 5, f"tool-use implemented by only {len(impl)} frameworks"


def test_pattern_context():
    cat = _catalog()
    ctx = cat.get_pattern_context("chain-of-thought")
    assert ctx["id"] == "chain-of-thought"
    assert "frameworks_implementing" in ctx
    assert "methodologies_using" in ctx


def test_examples_indexed():
    cat = _catalog()
    assert len(cat.examples_by_pattern.get("chain-of-thought", [])) > 0


def test_server_tools_registered():
    server = build_server(catalog_dir=os.environ.get("CATALOG_DIR"))
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    for expected in ("find_pattern", "get_pattern", "get_pattern_context",
                     "examples_for", "pattern_for_symptom", "recommend_recipe"):
        assert expected in names, f"missing tool: {expected}"


def test_find_pattern_returns_results():
    server = build_server(catalog_dir=os.environ.get("CATALOG_DIR"))
    hits = _call(server, "find_pattern", query="memory", limit=3)
    assert isinstance(hits, list) and len(hits) > 0
    assert "id" in hits[0] and "category" in hits[0]


def test_pattern_for_symptom_returns_anti_patterns():
    server = build_server(catalog_dir=os.environ.get("CATALOG_DIR"))
    hits = _call(server, "pattern_for_symptom", symptom="agent loops forever")
    assert isinstance(hits, list) and len(hits) > 0
    assert "anti_pattern" in hits[0]
