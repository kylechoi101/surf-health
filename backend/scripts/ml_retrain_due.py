#!/usr/bin/env python3
"""Decide whether the XGB challenger needs a retrain: have new lab results landed?

ML training is off on the daily run (2026-10-04), so the challenger only moves
when something dispatches daily-forecast.yml with run_ml=true. This script is
that something's test. It compares the official lab results in
``beach_day.parquet`` (every row with an ``exceeds_stv`` label, which is what
training fits on) against a marker of the labels the last training run saw.

Two modes:

- ``--write-marker``: run by daily-forecast.yml right after ML training.
  Writes ``ml_training_labels.json`` beside the curated data, so the data
  commit carries it.
- default (check): run by xgb-retrain.yml after every forecast run. Due when the
  label set differs from the marker, or when there is no marker. At most one
  retrain per Pacific day: a marker stamped today is never due, which also keeps
  the ML run's own completion from dispatching another one. Nothing is due
  after 21:00 Pacific: an ~80 min run would commit after midnight, stamp the
  next day's forecast and gate out the 9 AM run. The next morning's run checks
  again.

The fingerprint covers (beach_id, sample_date, exceeds_stv), so a corrected
label counts as a new result, and a row gained anywhere in history (counties
that report weeks late) counts too, not only a newer date.

Usage:
  python scripts/ml_retrain_due.py --curated ../data/curated/ --write-marker
  python scripts/ml_retrain_due.py --curated data/curated --github-output "$GITHUB_OUTPUT"
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pandas as pd

MARKER_NAME = "ml_training_labels.json"
PACIFIC = ZoneInfo("America/Los_Angeles")
LATEST_DISPATCH_HOUR_PT = 21


def label_summary(beach_day: pd.DataFrame) -> dict:
    """Row count, newest sample date and an order-independent hash of the labels."""
    rows = beach_day.loc[beach_day["exceeds_stv"].notna(), ["beach_id", "sample_date", "exceeds_stv"]]
    keys = pd.DataFrame(
        {
            "beach_id": rows["beach_id"].astype(str),
            "sample_date": pd.to_datetime(rows["sample_date"]).dt.strftime("%Y-%m-%d").fillna("NaT"),
            "exceeds_stv": rows["exceeds_stv"].astype(bool).astype(int).astype(str),
        }
    ).sort_values(["beach_id", "sample_date", "exceeds_stv"])
    lines = (keys["beach_id"] + "|" + keys["sample_date"] + "|" + keys["exceeds_stv"]).str.cat(sep="\n")
    return {
        "n_labels": int(len(keys)),
        "newest_sample_date": keys.loc[keys["sample_date"] != "NaT", "sample_date"].max() if len(keys) else None,
        "fingerprint": hashlib.sha256(lines.encode()).hexdigest(),
    }


def load_summary(curated: Path) -> dict:
    return label_summary(pd.read_parquet(curated / "beach_day.parquet", columns=["beach_id", "sample_date", "exceeds_stv"]))


def write_marker(curated: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    marker = {"trained_at": now.isoformat(timespec="seconds"), **load_summary(curated)}
    path = curated / MARKER_NAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(marker, indent=2) + "\n")
    tmp.replace(path)
    return marker


def retrain_due(curated: Path, now: datetime | None = None) -> dict:
    """``{"due": bool, "reason": str, ...counts}`` for the current curated data."""
    now = now or datetime.now(UTC)
    current = load_summary(curated)
    if now.astimezone(PACIFIC).hour >= LATEST_DISPATCH_HOUR_PT:
        return {"due": False, "reason": "too_late_in_pacific_day", **current}
    try:
        marker = json.loads((curated / MARKER_NAME).read_text())
        trained_at = datetime.fromisoformat(marker["trained_at"])
    except (OSError, ValueError, TypeError, KeyError):
        return {"due": True, "reason": "no_marker", **current}

    out = {
        **current,
        "marker_trained_at": marker.get("trained_at"),
        "new_labels": current["n_labels"] - int(marker.get("n_labels") or 0),
    }
    if trained_at.astimezone(PACIFIC).date() == now.astimezone(PACIFIC).date():
        return {"due": False, "reason": "already_trained_today", **out}
    if current["fingerprint"] == marker.get("fingerprint"):
        return {"due": False, "reason": "no_new_lab_results", **out}
    return {"due": True, "reason": "new_lab_results", **out}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--curated", type=Path, required=True)
    parser.add_argument("--write-marker", action="store_true", help="record the labels training just saw")
    parser.add_argument("--github-output", type=Path, help="append due=/reason= lines here (check mode)")
    args = parser.parse_args()

    if args.write_marker:
        marker = write_marker(args.curated)
        print(f"ml_retrain_due: marker written ({marker['n_labels']} labels, newest {marker['newest_sample_date']})")
        return 0

    result = retrain_due(args.curated)
    print("ml_retrain_due: " + json.dumps(result))
    if args.github_output:
        with args.github_output.open("a") as fh:
            fh.write(f"due={'true' if result['due'] else 'false'}\n")
            fh.write(f"reason={result['reason']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
