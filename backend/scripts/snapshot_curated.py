#!/usr/bin/env python
"""Freeze a content-hashed snapshot of the shipped curated artifacts.

Copies a fixed set of files out of ``data/curated/`` into a dated snapshot
directory and writes a ``MANIFEST.json`` recording, per file: sha256, byte
size, and (for parquets) row count, full column list, dtypes, and the min/max
of any date-like key column.

The snapshot is the "before" side of :mod:`diff_curated`, which every step of
the rebuild programme uses to prove it changed only what it intended to.

Usage::

    python scripts/snapshot_curated.py --out ../data/baseline/2026-08-07

Deliberately excluded: ``serving.sqlite`` (derived, 7.6MB) and every
``*.bak-*`` file (five ad-hoc vintages with no manifest — the thing this
script exists to replace).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# The shipped artifacts worth freezing. Order is the order they appear in the
# manifest and in diff reports.
SNAPSHOT_FILES: tuple[str, ...] = (
    "beach_day.parquet",
    "observations.parquet",
    "beaches.parquet",
    "forecast_history.parquet",
    "forecasts.parquet",
    "system_health.json",
    "serving_calibration.json",
    "model_version.json",
    "production_model.json",
)

# Columns whose min/max is worth recording as a date range, when present.
DATE_KEY_COLUMNS: tuple[str, ...] = (
    "sample_date",
    "forecast_date",
    "sample_time",
    "forecast_generated_at",
)

_HASH_CHUNK = 1 << 20


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_iso(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        if pd.isna(value):  # type: ignore[arg-type]
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def describe_parquet(path: Path) -> dict:
    frame = pd.read_parquet(path)
    ranges: dict[str, dict[str, str | None]] = {}
    for column in DATE_KEY_COLUMNS:
        if column not in frame.columns:
            continue
        series = frame[column].dropna()
        if series.empty:
            ranges[column] = {"min": None, "max": None}
            continue
        ranges[column] = {
            "min": _as_iso(series.min()),
            "max": _as_iso(series.max()),
        }
    return {
        "rows": int(len(frame)),
        "columns": [str(c) for c in frame.columns],
        "dtypes": {str(c): str(frame[c].dtype) for c in frame.columns},
        "date_ranges": ranges,
    }


def build_manifest_entry(path: Path) -> dict:
    entry: dict = {
        "sha256": sha256_of(path),
        "bytes": int(path.stat().st_size),
    }
    if path.suffix == ".parquet":
        entry.update(describe_parquet(path))
    return entry


def snapshot(source_dir: Path, out_dir: Path, files: tuple[str, ...]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "snapshot_created_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(source_dir),
        "files": {},
        "missing": [],
    }
    for name in files:
        src = source_dir / name
        if not src.exists():
            manifest["missing"].append(name)
            print(f"  MISSING {name}", file=sys.stderr)
            continue
        dst = out_dir / name
        shutil.copy2(src, dst)
        entry = build_manifest_entry(dst)
        manifest["files"][name] = entry
        rows = entry.get("rows")
        detail = f"{entry['bytes'] / 1e6:8.2f} MB"
        if rows is not None:
            detail += f"  {rows:>9,} rows x {len(entry['columns']):>3} cols"
        print(f"  {name:<32} {detail}  {entry['sha256'][:12]}")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data" / "curated",
        help="directory to snapshot (default: repo data/curated)",
    )
    parser.add_argument("--out", type=Path, required=True, help="snapshot directory")
    parser.add_argument(
        "--manifest-copy",
        type=Path,
        default=None,
        help="optional second path to write MANIFEST.json to (e.g. docs/baselines/)",
    )
    args = parser.parse_args(argv)

    source_dir: Path = args.source.resolve()
    out_dir: Path = args.out.resolve()
    if not source_dir.is_dir():
        parser.error(f"source dir not found: {source_dir}")

    print(f"snapshot {source_dir} -> {out_dir}")
    manifest = snapshot(source_dir, out_dir, SNAPSHOT_FILES)

    manifest_path = out_dir / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {manifest_path}")

    if args.manifest_copy is not None:
        copy_path: Path = args.manifest_copy.resolve()
        copy_path.parent.mkdir(parents=True, exist_ok=True)
        copy_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"wrote {copy_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
