"""FastMCP server exposing the catalog as MCP resources + tools.

Resources:
  Static (catalog-wide):
    catalog://stats         counts, version, source URL — single-call summary
    catalog://index         full enumeration of every entry (id+name+category)

  Per-entity (URI templates, resolved on demand):
    pattern://<id>          full pattern entry
    recipe://<id>           full recipe (abstract composition)
    framework://<id>        full framework (concrete composition)
    methodology://<id>      full methodology entry
    training://<id>         full training entry
    glossary://<term>       glossary term lookup (id, lowercased term, or expansion)

Tools (verbs an AI agent will actually call):
  Discovery / enumeration:
    catalog_info()                       single-call summary of what's in the catalog
    list_categories()                    14 pattern categories with counts
    list_patterns(category?)             enumerate patterns
    list_recipes(category?)              enumerate recipes
    list_frameworks(category?)           enumerate frameworks
    list_methodologies(category?)        enumerate methodologies
    list_trainings(cluster?)             enumerate training entries
    list_glossary_terms()                enumerate glossary terms
  Lookup (single entity by id):
    get_pattern(pattern_id)              full pattern body
    get_recipe(recipe_id)                recipe by id
    get_framework(framework_id)          framework by id
    get_methodology(methodology_id)      methodology by id
    get_training(training_id)            training entry by id
    glossary_term(term)                  glossary term lookup
  Search / cross-reference:
    find_pattern(query, limit?)          fuzzy search across name/aliases/intent
    search_text(query, kind?, limit?)    broader full-text across patterns/recipes/methodologies
    get_pattern_context(pattern_id)      reverse-index view (who uses/implements it)
    examples_for(pattern_id, framework?) code examples
    pattern_for_symptom(symptom)         anti-patterns matching the symptom + their fixes
    anti_patterns_in(category?)          list anti-patterns
  Heuristic recommenders:
    recommend_recipe(use_case, ...)      recipes + frameworks for a use case
    suggest_methodology(use_case)        methodologies for a use case
    recommend_training(goal)             training entries for a learning goal

Both stdio and streamable-HTTP transports are supported by the same `build_server`
function — the dispatch lives in __main__.py.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import __version__
from .catalog import Catalog, load_catalog


def _summary(entry: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: entry[k] for k in keys if k in entry}


def _stats(catalog: Catalog) -> dict[str, Any]:
    """Single-call catalog summary. Used by both `catalog://stats` and `catalog_info()`."""
    recipes = sum(1 for c in catalog.compositions.values() if c.get("kind") == "recipe")
    frameworks = sum(1 for c in catalog.compositions.values() if c.get("kind") == "framework")
    # glossary dict is multiply-indexed (by id, lowercased term, expansion); de-dup by id.
    glossary_count = len({e["id"] for e in catalog.glossary.values()})
    return {
        "version": __version__,
        "source_repo": "https://github.com/agentpatternscatalog/patterns",
        "patterns": len(catalog.patterns),
        "recipes": recipes,
        "frameworks": frameworks,
        "compositions_total": len(catalog.compositions),
        "methodologies": len(catalog.methodologies),
        "trainings": len(catalog.training),
        "glossary_terms": glossary_count,
        "examples_indexed": sum(len(v) for v in catalog.examples_by_pattern.values()),
        "categories": dict(Counter(p["category"] for p in catalog.patterns.values())),
    }


def _index(catalog: Catalog) -> dict[str, Any]:
    """Full enumeration. Same data callers would get from list_* tools, packed once."""
    by_category: dict[str, list[dict[str, str]]] = {}
    for p in catalog.patterns.values():
        by_category.setdefault(p["category"], []).append({"id": p["id"], "name": p["name"]})
    for cat in by_category:
        by_category[cat].sort(key=lambda x: x["id"])
    return {
        "patterns_by_category": by_category,
        "recipes": sorted(
            ({"id": c["id"], "name": c.get("name", c["id"])}
             for c in catalog.compositions.values() if c.get("kind") == "recipe"),
            key=lambda x: x["id"],
        ),
        "frameworks": sorted(
            ({"id": c["id"], "name": c.get("name", c["id"]), "category": c.get("category", "")}
             for c in catalog.compositions.values() if c.get("kind") == "framework"),
            key=lambda x: x["id"],
        ),
        "methodologies": sorted(
            ({"id": m["id"], "name": m.get("name", m["id"]), "category": m.get("category", "")}
             for m in catalog.methodologies.values()),
            key=lambda x: x["id"],
        ),
        "trainings": sorted(
            ({"id": t["id"], "name": t.get("name", t["id"]), "cluster": t.get("cluster", "")}
             for t in catalog.training.values()),
            key=lambda x: x["id"],
        ),
        "glossary_terms": sorted(
            ({"id": e["id"], "term": e["term"]}
             for e in {v["id"]: v for v in catalog.glossary.values()}.values()),
            key=lambda x: x["id"],
        ),
    }


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

    @mcp.resource("training://{training_id}")
    def training_resource(training_id: str) -> str:
        entry = catalog.training.get(training_id)
        if not entry:
            raise ValueError(f"unknown training entry: {training_id!r}")
        return json.dumps(entry, indent=2, ensure_ascii=False)

    @mcp.resource("glossary://{term}")
    def glossary_resource(term: str) -> str:
        # Lookup is case-insensitive on either id, full term, or expansion.
        entry = catalog.glossary.get(term) or catalog.glossary.get(term.lower())
        if not entry:
            raise ValueError(f"unknown glossary term: {term!r}")
        return json.dumps(entry, indent=2, ensure_ascii=False)

    # Static catalog-wide resources — single fetch gives a client the entire
    # surface area without enumerating tool calls.

    @mcp.resource("catalog://stats")
    def catalog_stats_resource() -> str:
        return json.dumps(_stats(catalog), indent=2, ensure_ascii=False)

    @mcp.resource("catalog://index")
    def catalog_index_resource() -> str:
        return json.dumps(_index(catalog), indent=2, ensure_ascii=False)

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

    # ----- discovery + enumeration ----------------------------------------

    @mcp.tool()
    def catalog_info() -> dict[str, Any]:
        """Single-call summary of what's in the catalog: counts of patterns /
        recipes / frameworks / methodologies / trainings / glossary terms,
        per-category pattern counts, server version, source repo URL.

        Use this as the entry point when first exploring the catalog — it lets
        the caller orient itself in one round-trip instead of enumerating
        every list_* tool."""
        return _stats(catalog)

    @mcp.tool()
    def list_categories() -> list[dict[str, Any]]:
        """List the pattern categories (e.g. 'memory', 'tool-use-environment',
        'anti-patterns', ...) with the number of patterns in each.

        Use this to plan a category-by-category exploration before fetching
        individual patterns."""
        cats = Counter(p["category"] for p in catalog.patterns.values())
        return [{"id": cat, "pattern_count": n} for cat, n in sorted(cats.items(), key=lambda x: -x[1])]

    @mcp.tool()
    def list_recipes(category: str | None = None) -> list[dict[str, Any]]:
        """List recipes (abstract compositions). Optional `category` matches
        substrings in the recipe's name or description (recipes don't carry
        a strict category enum the way frameworks do)."""
        entries = [c for c in catalog.compositions.values() if c.get("kind") == "recipe"]
        if category:
            q = category.lower()
            entries = [r for r in entries
                       if q in r.get("name", "").lower() or q in (r.get("description") or "").lower()]
        return [_summary(r, ("id", "name", "description", "status_in_practice"))
                for r in sorted(entries, key=lambda r: r["id"])]

    @mcp.tool()
    def list_methodologies(category: str | None = None) -> list[dict[str, Any]]:
        """List methodologies. Optional `category` filters by the methodology's
        category field (e.g. 'rag-construction', 'evaluation', 'coordination')."""
        entries = list(catalog.methodologies.values())
        if category:
            entries = [m for m in entries if m.get("category") == category]
        return [_summary(m, ("id", "name", "category", "summary", "intent", "maturity"))
                for m in sorted(entries, key=lambda m: (m.get("category", ""), m["id"]))]

    @mcp.tool()
    def list_trainings(cluster: str | None = None) -> list[dict[str, Any]]:
        """List training entries (curated learning paths). Optional `cluster`
        filters by cluster id (e.g. 'agent-learner', 'foundation-operator',
        'composer'). Each entry has steps, principles, inputs/outputs and
        unlocks_methodologies links."""
        entries = list(catalog.training.values())
        if cluster:
            entries = [t for t in entries if t.get("cluster") == cluster]
        return [_summary(t, ("id", "name", "cluster", "step", "summary", "intent",
                             "masterpiece", "maturity"))
                for t in sorted(entries, key=lambda t: (t.get("cluster", ""), t.get("step", 0), t["id"]))]

    @mcp.tool()
    def list_glossary_terms() -> list[dict[str, Any]]:
        """List all glossary terms (id, full term, expansion). Use glossary_term
        or the glossary://<term> resource to retrieve a single definition."""
        seen: dict[str, dict[str, Any]] = {}
        for entry in catalog.glossary.values():
            seen[entry["id"]] = entry
        return [{"id": e["id"], "term": e["term"], "expansion": e.get("expansion", "")}
                for e in sorted(seen.values(), key=lambda e: e["id"])]

    # ----- lookup (single entity by id) -----------------------------------

    @mcp.tool()
    def get_training(training_id: str) -> dict[str, Any]:
        """Return a training entry by id (e.g. 'tool-call-fluency',
        'judge-loop-design')."""
        entry = catalog.training.get(training_id)
        if not entry:
            return {"error": f"unknown training entry: {training_id!r}",
                    "available_count": len(catalog.training)}
        return entry

    @mcp.tool()
    def glossary_term(term: str) -> dict[str, Any]:
        """Look up a glossary term by id ('llm'), full term ('LLM'), or
        expansion ('Large Language Model'). Case-insensitive."""
        entry = catalog.glossary.get(term) or catalog.glossary.get(term.lower())
        if not entry:
            return {"error": f"unknown glossary term: {term!r}",
                    "available_count": len({e['id'] for e in catalog.glossary.values()})}
        return entry

    # ----- broader search -------------------------------------------------

    @mcp.tool()
    def search_text(
        query: str,
        kind: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Full-text search across patterns, recipes, frameworks, methodologies,
        and trainings — broader than `find_pattern` (which only hits
        name/aliases/intent on patterns). Optional `kind` restricts to one of:
        'pattern', 'recipe', 'framework', 'methodology', 'training'.

        Searches name + intent + summary + context + problem + solution +
        when_to_apply + description fields where present. Ranks by token-hit
        count, returns top `limit`."""
        q = query.lower().strip()
        tokens = [t for t in q.split() if len(t) > 2]
        if not tokens:
            return []

        SEARCH_FIELDS = ("name", "intent", "summary", "context", "problem",
                         "solution", "description", "when_to_apply")

        def score(entry: dict[str, Any]) -> int:
            haystack = " ".join(str(entry.get(f) or "") for f in SEARCH_FIELDS).lower()
            return sum(1 for t in tokens if t in haystack)

        out: list[dict[str, Any]] = []
        collections: list[tuple[str, dict[str, dict[str, Any]]]] = []
        if kind in (None, "pattern"):
            collections.append(("pattern", catalog.patterns))
        if kind in (None, "recipe"):
            collections.append(("recipe", {k: v for k, v in catalog.compositions.items() if v.get("kind") == "recipe"}))
        if kind in (None, "framework"):
            collections.append(("framework", {k: v for k, v in catalog.compositions.items() if v.get("kind") == "framework"}))
        if kind in (None, "methodology"):
            collections.append(("methodology", catalog.methodologies))
        if kind in (None, "training"):
            collections.append(("training", catalog.training))

        for kind_name, coll in collections:
            for entry in coll.values():
                s = score(entry)
                if s > 0:
                    out.append({
                        "kind": kind_name,
                        "id": entry["id"],
                        "name": entry.get("name", entry["id"]),
                        "category": entry.get("category", ""),
                        "intent": entry.get("intent") or entry.get("summary"),
                        "_score": s,
                    })
        out.sort(key=lambda r: (-r["_score"], r["id"]))
        for r in out:
            r.pop("_score", None)
        return out[:limit]

    # ----- heuristic recommenders -----------------------------------------

    @mcp.tool()
    def suggest_methodology(use_case: str, limit: int = 5) -> list[dict[str, Any]]:
        """Suggest methodologies for a given use case. Heuristic: token-overlap
        scoring against the methodology's name + intent + summary +
        when_to_apply fields. Returns top `limit` ranked by hit count, then by
        maturity ('stable' > 'beta' > 'experimental')."""
        q = use_case.lower().strip()
        tokens = [t for t in q.split() if len(t) > 2]
        if not tokens:
            return []

        maturity_rank = {"stable": 0, "beta": 1, "experimental": 2}

        scored: list[tuple[int, int, dict[str, Any]]] = []
        for m in catalog.methodologies.values():
            haystack = " ".join(str(m.get(f) or "") for f in
                                ("name", "intent", "summary", "when_to_apply",
                                 "category", "applies_to")).lower()
            hits = sum(1 for t in tokens if t in haystack)
            if hits == 0:
                continue
            mrank = maturity_rank.get(m.get("maturity", ""), 3)
            scored.append((hits, mrank, m))
        scored.sort(key=lambda x: (-x[0], x[1], x[2]["id"]))
        return [_summary(m, ("id", "name", "category", "summary", "intent",
                             "when_to_apply", "maturity"))
                for _, _, m in scored[:limit]]

    @mcp.tool()
    def recommend_training(goal: str, limit: int = 5) -> list[dict[str, Any]]:
        """Recommend training entries for a learning goal. Heuristic:
        token-overlap on name + intent + summary + when_to_apply, with a
        preference for lower-step entries (earlier in the curriculum) when
        scores tie. Returns top `limit`."""
        q = goal.lower().strip()
        tokens = [t for t in q.split() if len(t) > 2]
        if not tokens:
            return []

        scored: list[tuple[int, int, dict[str, Any]]] = []
        for t_entry in catalog.training.values():
            haystack = " ".join(str(t_entry.get(f) or "") for f in
                                ("name", "intent", "summary", "when_to_apply",
                                 "cluster", "principles")).lower()
            hits = sum(1 for tok in tokens if tok in haystack)
            if hits == 0:
                continue
            step = int(t_entry.get("step") or 99)
            scored.append((hits, step, t_entry))
        scored.sort(key=lambda x: (-x[0], x[1], x[2]["id"]))
        return [_summary(t, ("id", "name", "cluster", "step", "summary",
                             "intent", "when_to_apply", "unlocks_methodologies"))
                for _, _, t in scored[:limit]]

    return mcp
