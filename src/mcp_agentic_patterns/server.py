"""FastMCP server exposing the catalog as MCP resources + tools.

Resources (one URI per entity, addressable for retrieval):
  pattern://<id>          full pattern entry
  recipe://<id>           full recipe (abstract composition)
  framework://<id>        full framework (concrete composition)
  methodology://<id>      full methodology entry

Tools (verbs an AI agent will actually call):
  find_pattern(query, limit?)          fuzzy search across name/aliases/intent
  get_pattern(pattern_id)              full pattern body
  list_patterns(category?)             enumerate patterns, optionally by category
  get_pattern_context(pattern_id)      reverse-index view (who uses/implements it)
  examples_for(pattern_id, framework?) code examples
  pattern_for_symptom(symptom)         anti-patterns matching the symptom + their fixes
  anti_patterns_in(category?)          list anti-patterns
  get_recipe(recipe_id)                recipe by id
  get_framework(framework_id)          framework by id
  list_frameworks(category?)           enumerate frameworks
  get_methodology(methodology_id)      methodology by id
  recommend_recipe(use_case, ...)      heuristic recommender

Both stdio and streamable-HTTP transports are supported by the same `build_server`
function — the dispatch lives in __main__.py.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from .catalog import Catalog, load_catalog


def _summary(entry: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: entry[k] for k in keys if k in entry}


def build_server(
    catalog_dir: str | None = None,
    *,
    host: str = "0.0.0.0",
    port: int = 8080,
    refresh: bool = False,
) -> FastMCP:
    """Construct the FastMCP server bound to a loaded catalog.

    `host` and `port` are only consulted by the streamable-HTTP transport; they
    are ignored for stdio (since the MCP SDK 1.x exposes them via the FastMCP
    constructor rather than `run()` kwargs).

    `refresh=True` forces a re-fetch of the catalog from GitHub even if a cached
    copy exists.
    """
    catalog: Catalog = load_catalog(catalog_dir, refresh=refresh)
    mcp = FastMCP("agentic-patterns", host=host, port=port)

    # ----- resources --------------------------------------------------------

    @mcp.resource("pattern://{pattern_id}")
    def pattern_resource(pattern_id: str) -> str:
        entry = catalog.patterns.get(pattern_id)
        if not entry:
            raise ValueError(f"unknown pattern: {pattern_id!r}")
        return json.dumps(entry, indent=2, ensure_ascii=False)

    @mcp.resource("recipe://{recipe_id}")
    def recipe_resource(recipe_id: str) -> str:
        entry = catalog.compositions.get(recipe_id)
        if not entry or entry.get("kind") != "recipe":
            raise ValueError(f"unknown recipe: {recipe_id!r}")
        return json.dumps(entry, indent=2, ensure_ascii=False)

    @mcp.resource("framework://{framework_id}")
    def framework_resource(framework_id: str) -> str:
        entry = catalog.compositions.get(framework_id)
        if not entry or entry.get("kind") != "framework":
            raise ValueError(f"unknown framework: {framework_id!r}")
        return json.dumps(entry, indent=2, ensure_ascii=False)

    @mcp.resource("methodology://{methodology_id}")
    def methodology_resource(methodology_id: str) -> str:
        entry = catalog.methodologies.get(methodology_id)
        if not entry:
            raise ValueError(f"unknown methodology: {methodology_id!r}")
        return json.dumps(entry, indent=2, ensure_ascii=False)

    # ----- tools ------------------------------------------------------------

    @mcp.tool()
    def find_pattern(query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search patterns by id, name, alias, or intent. Returns top matches.

        Ranks substring matches by where they hit (id > name > alias > intent),
        case-insensitive, with the most specific match first.
        """
        q = query.lower().strip()
        scored: list[tuple[int, dict[str, Any]]] = []
        for entry in catalog.patterns.values():
            score = 0
            if q in entry["id"].lower():
                score += 100
            if q in entry["name"].lower():
                score += 50
            for alias in entry.get("aliases", []) or []:
                if q in alias.lower():
                    score += 25
                    break
            if q in (entry.get("intent") or "").lower():
                score += 10
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda s: -s[0])
        return [_summary(e, ("id", "name", "category", "intent", "status_in_practice")) for _, e in scored[:limit]]

    @mcp.tool()
    def get_pattern(pattern_id: str) -> dict[str, Any]:
        """Return the full body of a pattern by id."""
        entry = catalog.patterns.get(pattern_id)
        if not entry:
            return {"error": f"unknown pattern: {pattern_id!r}", "available_count": len(catalog.patterns)}
        return entry

    @mcp.tool()
    def list_patterns(category: str | None = None) -> list[dict[str, Any]]:
        """List patterns, optionally filtered by category (e.g. 'tool-use-environment')."""
        entries = catalog.patterns.values()
        if category:
            entries = [e for e in entries if e.get("category") == category]
        return [_summary(e, ("id", "name", "category", "intent", "status_in_practice"))
                for e in sorted(entries, key=lambda e: (e["category"], e["id"]))]

    @mcp.tool()
    def get_pattern_context(pattern_id: str) -> dict[str, Any]:
        """Reverse-index view of a pattern: who implements it (frameworks), who
        uses it (recipes, methodologies), and what anti-patterns oppose it."""
        return catalog.get_pattern_context(pattern_id) or {"error": f"unknown pattern: {pattern_id!r}"}

    @mcp.tool()
    def examples_for(pattern_id: str, framework: str | None = None) -> list[dict[str, Any]]:
        """Get code examples for a pattern, optionally filtered to one framework
        (e.g. 'langchain', 'dspy', 'claude-agent-sdk', 'pseudo')."""
        examples = catalog.examples_by_pattern.get(pattern_id, [])
        if framework:
            examples = [e for e in examples if e.get("framework") == framework]
        return examples

    @mcp.tool()
    def pattern_for_symptom(symptom: str) -> list[dict[str, Any]]:
        """Given an observed symptom (e.g. 'agent loops forever', 'tool calls
        reference functions that do not exist'), return likely anti-patterns and
        the positive patterns that fix them.

        Note: until structured `symptoms` fields land on anti-patterns (catalog
        task #3), this falls back to keyword search across each anti-pattern's
        name, intent, and problem text.
        """
        q = symptom.lower().strip()
        matches: list[dict[str, Any]] = []
        for entry in catalog.patterns.values():
            if entry.get("category") != "anti-patterns":
                continue
            haystack = " ".join([
                entry.get("name", ""),
                entry.get("intent", ""),
                entry.get("problem", ""),
            ]).lower()
            # Score by token coverage so multi-word symptoms still match.
            tokens = [t for t in q.split() if len(t) > 2]
            hits = sum(1 for t in tokens if t in haystack)
            if hits == 0:
                continue
            fixes = [rel["pattern"] for rel in entry.get("related", []) or []
                     if rel.get("relation") == "alternative-to" and rel.get("pattern") in catalog.patterns]
            matches.append({
                "anti_pattern": entry["id"],
                "name": entry["name"],
                "intent": entry.get("intent"),
                "fixes": fixes,
                "_score": hits,
            })
        matches.sort(key=lambda m: -m["_score"])
        for m in matches:
            m.pop("_score", None)
        return matches[:10]

    @mcp.tool()
    def anti_patterns_in(category: str | None = None) -> list[dict[str, Any]]:
        """List anti-patterns. The catalog's `anti-patterns` category holds all
        of them; the optional `category` argument lets a caller pass a topical
        keyword (matched against name/intent) for narrowing."""
        anti = [e for e in catalog.patterns.values() if e.get("category") == "anti-patterns"]
        if category:
            q = category.lower()
            anti = [e for e in anti if q in e["name"].lower() or q in (e.get("intent") or "").lower()]
        return [_summary(e, ("id", "name", "intent", "status_in_practice"))
                for e in sorted(anti, key=lambda e: e["id"])]

    @mcp.tool()
    def get_recipe(recipe_id: str) -> dict[str, Any]:
        """Return a recipe (abstract composition) by id."""
        entry = catalog.compositions.get(recipe_id)
        if not entry or entry.get("kind") != "recipe":
            return {"error": f"unknown recipe: {recipe_id!r}"}
        return entry

    @mcp.tool()
    def get_framework(framework_id: str) -> dict[str, Any]:
        """Return a framework (concrete composition) by id."""
        entry = catalog.compositions.get(framework_id)
        if not entry or entry.get("kind") != "framework":
            return {"error": f"unknown framework: {framework_id!r}"}
        return entry

    @mcp.tool()
    def list_frameworks(category: str | None = None) -> list[dict[str, Any]]:
        """List frameworks. Optional `category` filters by composition category
        (orchestration-framework, agent-sdk, coding-agent, voice-conversational, ...)."""
        entries = [c for c in catalog.compositions.values() if c.get("kind") == "framework"]
        if category:
            entries = [c for c in entries if c.get("category") == category]
        return [_summary(c, ("id", "name", "category", "vendor", "status", "build_surface", "intent"))
                for c in sorted(entries, key=lambda c: c["id"])]

    @mcp.tool()
    def get_methodology(methodology_id: str) -> dict[str, Any]:
        """Return a methodology entry by id."""
        entry = catalog.methodologies.get(methodology_id)
        if not entry:
            return {"error": f"unknown methodology: {methodology_id!r}"}
        return entry

    @mcp.tool()
    def recommend_recipe(
        use_case: str,
        scale: str = "team-tool",
        regulated: bool = False,
    ) -> list[dict[str, Any]]:
        """Recommend recipes and frameworks for a use case + constraints.

        Heuristic v1: maps `use_case` to a composition category (coding-agent,
        rag, voice-conversational, browser-computer-use, research-agent,
        agent-sdk, orchestration-framework, conversational-bot) and returns
        top recipes + a few frameworks. A proper facet-based recommender is
        catalog task #7.
        """
        use_case = use_case.lower()
        category_map = {
            "coding": "coding-agent", "code": "coding-agent", "ide": "coding-agent",
            "rag": "rag", "retrieval": "rag", "search": "rag",
            "voice": "voice-conversational", "phone": "voice-conversational",
            "browser": "browser-computer-use", "web": "browser-computer-use",
            "research": "research-agent", "deep-research": "research-agent",
            "sdk": "agent-sdk",
            "orchestration": "orchestration-framework", "workflow": "workflow-engine",
            "chat": "conversational-bot", "chatbot": "conversational-bot",
        }
        target = next((cat for key, cat in category_map.items() if key in use_case), None)
        recipes = [c for c in catalog.compositions.values() if c.get("kind") == "recipe"]
        frameworks = [c for c in catalog.compositions.values()
                      if c.get("kind") == "framework" and (target is None or c.get("category") == target)]
        # Recipes don't carry a category enum like frameworks do; rank by name match.
        recipes_ranked = sorted(recipes, key=lambda r: (0 if target and target.replace("-", " ") in r.get("name", "").lower() else 1, r["id"]))
        # Mature frameworks first; if regulated, prefer those declaring safety patterns.
        def fw_score(c: dict[str, Any]) -> tuple[int, int, str]:
            status_rank = {"active": 0, "maintenance": 1, "deprecated": 2}.get(c.get("status", ""), 3)
            safety = 0
            if regulated:
                safety_members = sum(1 for m in c.get("members", []) if "policy" in m.get("pattern", "") or "guardrail" in m.get("pattern", ""))
                safety = -safety_members
            return (status_rank, safety, c["id"])
        return {
            "use_case": use_case,
            "resolved_category": target,
            "scale": scale,
            "regulated": regulated,
            "top_recipes": [_summary(r, ("id", "name", "description", "status_in_practice")) for r in recipes_ranked[:3]],
            "top_frameworks": [_summary(c, ("id", "name", "vendor", "category", "status", "build_surface"))
                               for c in sorted(frameworks, key=fw_score)[:5]],
        }  # type: ignore[return-value]

    return mcp
