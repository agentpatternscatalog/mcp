#!/usr/bin/env python3
"""Copy source shards from the sibling catalog repo into the package's data/ dir.

Run this before `hatch build` / `uv build` so the wheel ships with frozen catalog
data and works offline. The hosted instance reads the live repo via CATALOG_DIR
instead and does not depend on this snapshot.

Usage:
    python scripts/bundle_catalog.py [--catalog-dir PATH]
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TARGET = HERE / "src" / "mcp_agentic_patterns" / "data"
SHARD_DIRS = ("patterns-src", "compositions-src", "methodologies-src", "examples-src", "training-src")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--catalog-dir",
        default=str(HERE.parent.parent / "agent-patterns-catalog"),
        help="Path to the agentic patterns catalog repo (default: sibling directory).",
    )
    args = parser.parse_args()

    source = Path(args.catalog_dir)
    if not (source / "patterns-src").is_dir():
        raise SystemExit(f"no catalog at {source}: missing patterns-src/")

    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)

    for sub in SHARD_DIRS:
        src = source / sub
        if not src.is_dir():
            print(f"  (skip: {sub} not present)")
            continue
        dst = TARGET / sub
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))
        n = len(list(dst.glob("*.json")))
        print(f"  bundled {sub}: {n} shard(s)")

    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
