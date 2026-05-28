"""Catalog data loader and reverse-index builder.

Loads patterns, compositions (recipes + frameworks), methodologies, examples, and
training entries from a directory laid out like the agentpatternscatalog/patterns
repository (i.e. patterns-src/, compositions-src/, methodologies-src/, examples-src/,
training-src/ — each a directory of category shards).

Catalog data sources, in priority order:

  * `catalog_dir` argument or `CATALOG_DIR` env var — points at a live checkout of
    the catalog repo. Used during development.
  * Sibling repo at `../agent-patterns-catalog/` next to this repo's working tree.
  * On-disk cache at `~/.cache/mcp-agentic-patterns/patterns-main/`, populated by a
    one-time download of the upstream catalog tarball.
  * Fresh fetch of https://github.com/agentpatternscatalog/patterns (tarball of the
    main branch), extracted into the cache directory. This is the path a brand-new
    `git clone + uv sync + mcp-agentic-patterns` invocation follows.
  * Bundled package data at `mcp_agentic_patterns/data/` — populated by
    `scripts/bundle_catalog.py` before each PyPI release. Used by the published
    wheel so installs work fully offline.

A startup-time reverse index gives O(1) lookup for "who implements this pattern",
"which methodologies use it", "which anti-patterns oppose it", etc. — what would
otherwise be repeated cross-shard scans on every MCP tool call.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tarfile
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

CATALOG_REPO = "agentpatternscatalog/patterns"
CATALOG_BRANCH = "main"
CATALOG_TARBALL_URL = (
    f"https://codeload.github.com/{CATALOG_REPO}/tar.gz/refs/heads/{CATALOG_BRANCH}"
)
CACHE_SUBDIR = "patterns-main"


@dataclass
class Catalog:
    """In-memory view of the agentic patterns catalog with reverse indexes."""

    root: Path

    patterns: dict[str, dict[str, Any]] = field(default_factory=dict)
    compositions: dict[str, dict[str, Any]] = field(default_factory=dict)
    methodologies: dict[str, dict[str, Any]] = field(default_factory=dict)
    training: dict[str, dict[str, Any]] = field(default_factory=dict)
    examples_by_pattern: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    # Reverse indexes — built once at startup, used by every tool call.
    frameworks_implementing: dict[str, list[str]] = field(default_factory=dict)
    recipes_including: dict[str, list[str]] = field(default_factory=dict)
    methodologies_using: dict[str, list[str]] = field(default_factory=dict)
    anti_patterns_defended_by: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._load()
        self._build_reverse_index()

    # ----- loading --------------------------------------------------------

    def _load(self) -> None:
        for shard in sorted((self.root / "patterns-src").glob("*.json")):
            for entry in json.loads(shard.read_text())["patterns"]:
                self.patterns[entry["id"]] = entry
        for shard in sorted((self.root / "compositions-src").glob("*.json")):
            shard_data = json.loads(shard.read_text())
            items = shard_data if isinstance(shard_data, list) else shard_data.get("compositions", [])
            for entry in items:
                if isinstance(entry, dict) and "id" in entry:
                    self.compositions[entry["id"]] = entry
        for shard in sorted((self.root / "methodologies-src").glob("*.json")):
            for entry in json.loads(shard.read_text()).get("methodologies", []):
                self.methodologies[entry["id"]] = entry
        training_dir = self.root / "training-src"
        if training_dir.exists():
            for shard in sorted(training_dir.glob("*.json")):
                for entry in json.loads(shard.read_text())["patterns"]:
                    self.training[entry["id"]] = entry
        examples_dir = self.root / "examples-src"
        if examples_dir.exists():
            for shard in sorted(examples_dir.glob("*.json")):
                for entry in json.loads(shard.read_text())["patterns"]:
                    self.examples_by_pattern.setdefault(entry["pattern_id"], []).extend(
                        entry.get("examples", [])
                    )

    # ----- reverse index --------------------------------------------------

    def _build_reverse_index(self) -> None:
        fw_impl: dict[str, list[str]] = defaultdict(list)
        recipe_inc: dict[str, list[str]] = defaultdict(list)
        for comp_id, comp in self.compositions.items():
            kind = comp.get("kind")
            for member in comp.get("members", []):
                pid = member.get("pattern")
                if not pid:
                    continue
                if kind == "framework":
                    fw_impl[pid].append(comp_id)
                elif kind == "recipe":
                    recipe_inc[pid].append(comp_id)
        self.frameworks_implementing = dict(fw_impl)
        self.recipes_including = dict(recipe_inc)

        meth_use: dict[str, list[str]] = defaultdict(list)
        for meth_id, meth in self.methodologies.items():
            for pid in meth.get("related_patterns", []) or []:
                meth_use[pid].append(meth_id)
            for step in meth.get("steps", []) or []:
                for pid in step.get("uses_patterns", []) or []:
                    if meth_id not in meth_use[pid]:
                        meth_use[pid].append(meth_id)
        self.methodologies_using = dict(meth_use)

        # Anti-patterns defended-by: until task #3 lands an explicit `fixes` field,
        # derive from `related[]` edges where an anti-pattern names a positive
        # pattern via "alternative-to" — this is the existing weak signal.
        defended: dict[str, list[str]] = defaultdict(list)
        for pid, pattern in self.patterns.items():
            if pattern.get("category") != "anti-patterns":
                continue
            for rel in pattern.get("related", []) or []:
                if rel.get("relation") in {"alternative-to", "fixed-by"}:
                    target = rel.get("pattern")
                    if target and target in self.patterns:
                        defended[target].append(pid)
        self.anti_patterns_defended_by = dict(defended)

    # ----- public lookups -------------------------------------------------

    def get_pattern_context(self, pattern_id: str) -> dict[str, Any]:
        """Full reverse-index view of a single pattern."""
        if pattern_id not in self.patterns:
            return {}
        return {
            "id": pattern_id,
            "name": self.patterns[pattern_id]["name"],
            "category": self.patterns[pattern_id]["category"],
            "frameworks_implementing": self.frameworks_implementing.get(pattern_id, []),
            "recipes_including": self.recipes_including.get(pattern_id, []),
            "methodologies_using": self.methodologies_using.get(pattern_id, []),
            "anti_patterns_defended_against": self.anti_patterns_defended_by.get(pattern_id, []),
            "example_count": len(self.examples_by_pattern.get(pattern_id, [])),
            "example_frameworks": sorted({e["framework"] for e in self.examples_by_pattern.get(pattern_id, [])}),
        }


# ----- catalog discovery / fetch ------------------------------------------

def _default_cache_root() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "mcp-agentic-patterns"


def _has_catalog_layout(path: Path) -> bool:
    return (path / "patterns-src").is_dir()


def fetch_catalog_from_github(cache_root: Path | None = None) -> Path:
    """Download the upstream catalog tarball and extract it into the cache.

    Idempotent — wipes any existing ``<cache_root>/patterns-main/`` first so the
    extracted tree matches the freshly fetched archive.

    Returns the path to the extracted catalog root (which contains
    ``patterns-src/`` etc.).
    """
    cache_root = cache_root or _default_cache_root()
    cache_root.mkdir(parents=True, exist_ok=True)
    target = cache_root / CACHE_SUBDIR

    print(f"[mcp-agentic-patterns] fetching catalog from {CATALOG_TARBALL_URL}", file=sys.stderr)
    with urllib.request.urlopen(CATALOG_TARBALL_URL, timeout=60) as response:
        data = response.read()

    if target.exists():
        import shutil
        shutil.rmtree(target)
    target.mkdir(parents=True)

    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        # GitHub tarballs nest everything under '<repo>-<branch>/'. Strip that
        # first component so target/ contains patterns-src/ directly.
        members = tar.getmembers()
        top = {m.name.split("/", 1)[0] for m in members if "/" in m.name or m.isdir()}
        if len(top) != 1:
            raise RuntimeError(f"unexpected tarball layout (top-level dirs: {top})")
        prefix = next(iter(top)) + "/"
        for member in members:
            if not member.name.startswith(prefix):
                continue
            member.name = member.name[len(prefix):]
            if member.name:
                tar.extract(member, target)  # noqa: S202 — trusted GitHub source

    if not _has_catalog_layout(target):
        raise RuntimeError(f"fetched archive at {target} does not contain patterns-src/")
    print(f"[mcp-agentic-patterns] cached catalog at {target}", file=sys.stderr)
    return target


def resolve_catalog_dir(
    explicit: str | None = None,
    *,
    refresh: bool = False,
    cache_root: Path | None = None,
) -> Path:
    """Resolve the catalog directory in priority order:

    1. ``explicit`` argument (``--catalog-dir``)
    2. ``CATALOG_DIR`` env var
    3. sibling ``../agent-patterns-catalog/`` next to the repo working tree
    4. on-disk cache (unless ``refresh=True``)
    5. fresh GitHub fetch into the cache
    6. bundled package data (only present in published wheels)

    Set ``refresh=True`` (or env ``MCP_CATALOG_REFRESH=1``) to skip the cache and
    force a re-download from GitHub.
    """
    if explicit:
        return Path(explicit)
    env = os.environ.get("CATALOG_DIR")
    if env:
        return Path(env)

    # parents[3] from src/mcp_agentic_patterns/catalog.py == the directory that
    # contains this repo's working tree. A sibling 'agent-patterns-catalog'
    # checkout there is the dev convention (matches CLAUDE.md guidance).
    sibling = Path(__file__).resolve().parents[3] / "agent-patterns-catalog"
    if _has_catalog_layout(sibling):
        return sibling

    if not refresh and os.environ.get("MCP_CATALOG_REFRESH", "").lower() in {"1", "true", "yes"}:
        refresh = True

    cache_root = cache_root or _default_cache_root()
    cached = cache_root / CACHE_SUBDIR
    if not refresh and _has_catalog_layout(cached):
        return cached

    # Try a live fetch. If that fails (offline, GitHub down), fall back to bundled
    # data or, last resort, a stale cache.
    try:
        return fetch_catalog_from_github(cache_root)
    except Exception as exc:  # noqa: BLE001 — fall through to other sources
        print(f"[mcp-agentic-patterns] GitHub fetch failed: {exc}", file=sys.stderr)
        if _has_catalog_layout(cached):
            print(f"[mcp-agentic-patterns] using stale cache at {cached}", file=sys.stderr)
            return cached
        bundled = Path(str(files("mcp_agentic_patterns") / "data"))
        if _has_catalog_layout(bundled):
            print(f"[mcp-agentic-patterns] using bundled data at {bundled}", file=sys.stderr)
            return bundled
        raise SystemExit(
            "no catalog data found and GitHub fetch failed. "
            "Set CATALOG_DIR or pass --catalog-dir to point at a local checkout of "
            f"https://github.com/{CATALOG_REPO}, or install a published wheel "
            "(bundled data)."
        )


def load_catalog(catalog_dir: str | None = None, *, refresh: bool = False) -> Catalog:
    return Catalog(root=resolve_catalog_dir(catalog_dir, refresh=refresh))
