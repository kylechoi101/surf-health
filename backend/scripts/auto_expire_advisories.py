#!/usr/bin/env python3
"""Run G.2 auto-expire on data/curated/advisories.parquet.

Standalone wrapper around `auto_expire_zombie_advisories()` so the
GitHub Actions workflow can demote stale 'active' rows BEFORE the
audit step reads the parquet (otherwise the audit gate fires on
zombies the snapshot bake would have expired moments later).

Intended sequence in .github/workflows/daily-forecast.yml:
  1. Fetch BeachWatch + county scrapers
  2. (this script) — demote zombies in-place
  3. Audit + audit gate (G.4)
  4. Build serving snapshot (the auto_expire there is now a no-op
     defensive double-check)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from app.data.pipeline.serving_snapshot import auto_expire_zombie_advisories


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--advisories", type=Path,
                   default=Path("../data/curated/advisories.parquet"),
                   help="path to advisories.parquet")
    args = p.parse_args()

    path: Path = args.advisories.resolve()
    if not path.exists():
        print(f"error: advisories parquet not found: {path}", file=sys.stderr)
        return 2

    df = pd.read_parquet(path)
    before_active = int((df.get("status") == "active").sum()) if "status" in df.columns else 0
    new_df, n_expired = auto_expire_zombie_advisories(df)
    after_active = int((new_df.get("status") == "active").sum()) if "status" in new_df.columns else 0

    if n_expired > 0:
        new_df.to_parquet(path, index=False)
        print(f"[G.2 auto-expire] demoted {n_expired} zombie advisories "
              f"(active: {before_active} → {after_active})")
    else:
        print(f"[G.2 auto-expire] no zombies to demote (active: {before_active})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
