# mcp-agentic-patterns

An MCP (Model Context Protocol) server that exposes the [Agentic Patterns Catalog](https://agentpatternscatalog.org) — patterns, compositions (recipes + frameworks), methodologies, anti-patterns and code examples — as resources and tools for AI coding agents like Claude Code, Cursor, Cline and Claude Desktop.

Catalog data is sourced from <https://github.com/agentpatternscatalog/patterns>.

## Run it locally (today)

```bash
git clone https://github.com/agentpatternscatalog/mcp.git
cd mcp
uv sync                      # or: python -m venv .venv && pip install -e .
uv run mcp-agentic-patterns  # stdio transport (default)
```

The first run downloads the catalog tarball from `github.com/agentpatternscatalog/patterns` into `~/.cache/mcp-agentic-patterns/patterns-main/` and reuses it on subsequent runs. No network needed after the first start.

Refresh the cached catalog:

```bash
uv run mcp-agentic-patterns --refresh-catalog
# or:  MCP_CATALOG_REFRESH=1 uv run mcp-agentic-patterns
```

Point at a local checkout instead (skips the network entirely):

```bash
uv run mcp-agentic-patterns --catalog-dir /path/to/agent-patterns-catalog
# or:  CATALOG_DIR=/path/to/agent-patterns-catalog uv run mcp-agentic-patterns
```

Resolution priority: `--catalog-dir` arg → `CATALOG_DIR` env → sibling `../agent-patterns-catalog/` checkout → on-disk cache → fresh GitHub fetch → bundled package data.

## Wire it into your MCP client

Claude Desktop, Claude Code, Cursor, Cline (and other MCP clients) all read a `mcpServers` config block. Point them at the local checkout:

```json
{
  "mcpServers": {
    "agentic-patterns": {
      "command": "uv",
      "args": [
        "--directory", "/abs/path/to/mcp",
        "run", "mcp-agentic-patterns"
      ]
    }
  }
}
```

Or, after `pip install -e .`:

```json
{
  "mcpServers": {
    "agentic-patterns": {
      "command": "mcp-agentic-patterns"
    }
  }
}
```

## HTTP transport

For non-stdio MCP clients, run the server over streamable-HTTP:

```bash
uv run mcp-agentic-patterns http --host 0.0.0.0 --port 8080
```

## Tools

| Tool | What it does |
|---|---|
| `find_pattern(query, limit?)` | Fuzzy search across name, alias, intent |
| `get_pattern(id)` | Full pattern body |
| `list_patterns(category?)` | Enumerate patterns, optionally by category |
| `get_pattern_context(id)` | Reverse-index view: who implements it, who uses it, what opposes it |
| `examples_for(pattern_id, framework?)` | Code examples for a pattern |
| `pattern_for_symptom(symptom)` | Given an observed symptom, suggest anti-patterns + fix patterns |
| `anti_patterns_in(category?)` | List anti-patterns |
| `get_recipe(id)` / `get_framework(id)` / `list_frameworks(category?)` | Composition lookups |
| `get_methodology(id)` | Methodology entry |
| `recommend_recipe(use_case, scale?, regulated?)` | Heuristic recommender |

## Resources

| URI | Body |
|---|---|
| `pattern://<id>` | Pattern entry as JSON |
| `recipe://<id>` | Recipe entry as JSON |
| `framework://<id>` | Framework entry as JSON |
| `methodology://<id>` | Methodology entry as JSON |

## Develop

```bash
uv sync
uv run pytest tests
```

The smoke tests look for a sibling `../agent-patterns-catalog/` checkout if `CATALOG_DIR` isn't set; otherwise they exercise the cached / GitHub-fetched copy.

## License

MIT (this server). The catalog data itself is CC BY 4.0 — see <https://github.com/agentpatternscatalog/patterns>.
