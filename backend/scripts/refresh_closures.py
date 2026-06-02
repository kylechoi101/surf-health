"""Build the public closures feed (data/curated/closures.json).

Run hourly (after the county-advisory scrape) to pool currently-active beach
closures into a tiny public JSON the mobile app fetches on a background
schedule. The app does the proximity check + dedup ON-DEVICE — no user data,
no push tokens, no locations are ever sent to the server.

Usage:
    python scripts/refresh_closures.py [--curated DIR] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.core.config import get_settings
from app.data.pipeline.closures import build_closures_feed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--curated", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    curated = args.curated or Path(get_settings().curated_dir)
    out = args.out or (curated / "closures.json")

    advisories = pd.read_parquet(curated / "advisories.parquet")
    beaches = pd.read_parquet(curated / "beaches.parquet")
    feed = build_closures_feed(advisories, beaches)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "count": len(feed),
        "closures": feed,
    }
    out.write_text(json.dumps(payload, separators=(",", ":"), default=str))
    print(f"[closures] wrote {len(feed)} active closures -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
