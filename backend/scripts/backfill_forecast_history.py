"""One-time seed of data/curated/forecast_history.parquet from git history.

Every daily run commits ``forecasts.parquet``; this walks those commits and
reconstructs the served-forecast log that the accountability loop
(``app/ml/served_metrics.py``) scores against later lab results. Going forward
the daily pipeline appends in place; re-running this script is idempotent —
rows merge on (beach_id, forecast_date, forecast_generated_at).

Uses subprocess git directly (binary-safe blob reads).

Usage (from backend/):
  python scripts/backfill_forecast_history.py --curated ../data/curated/
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path

import pandas as pd

from app.ml.served_metrics import _HISTORY_COLUMNS, HISTORY_FILE

REL_PATH = "data/curated/forecasts.parquet"


def _repo_root(start: Path) -> Path:
    return Path(
        subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )


def _commits_touching(repo_root: Path) -> list[tuple[str, str]]:
    """[(sha, commit ISO timestamp)] for every commit touching the forecast."""
    out = subprocess.run(
        ["git", "-C", str(repo_root), "log", "--format=%H %cI", "--", REL_PATH],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    commits = []
    for line in out.splitlines():
        parts = line.strip().split(" ", 1)
        if len(parts) == 2:
            commits.append((parts[0], parts[1]))
    return commits


def _blob(repo_root: Path, sha: str) -> bytes | None:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "blob", f"{sha}:{REL_PATH}"],
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 and result.stdout else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curated", type=Path, default=Path("../data/curated/"))
    args = parser.parse_args(argv)

    repo_root = _repo_root(args.curated.resolve())
    commits = _commits_touching(repo_root)
    print(f"{len(commits)} commits touch {REL_PATH}", file=sys.stderr)

    frames: list[pd.DataFrame] = []
    skipped = 0
    for sha, committed_at in commits:
        blob = _blob(repo_root, sha)
        if blob is None:
            skipped += 1
            continue
        try:
            frame = pd.read_parquet(io.BytesIO(blob))
        except Exception:  # noqa: BLE001 — a corrupt historical blob is skippable
            skipped += 1
            continue
        if frame.empty or "beach_id" not in frame.columns or "forecast_date" not in frame.columns:
            skipped += 1
            continue
        # Legacy schema tolerance: older files predate some columns.
        if "p_exceed_raw" not in frame.columns:
            frame["p_exceed_raw"] = frame.get("p_exceed")
        if "p_exceed_precal" not in frame.columns:
            frame["p_exceed_precal"] = frame["p_exceed_raw"]
        if "forecast_generated_at" not in frame.columns or frame["forecast_generated_at"].isna().all():
            frame["forecast_generated_at"] = committed_at
        for column in _HISTORY_COLUMNS:
            if column not in frame.columns:
                frame[column] = None
        frames.append(frame[_HISTORY_COLUMNS])

    if not frames:
        print("No readable historical forecasts found; nothing to do.", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    for column in ("p_exceed", "p_exceed_raw", "p_exceed_precal", "sample_age_days"):
        combined[column] = pd.to_numeric(combined[column], errors="coerce")

    history_path = args.curated / HISTORY_FILE
    if history_path.exists():
        combined = pd.concat([pd.read_parquet(history_path), combined], ignore_index=True)
    combined = combined.drop_duplicates(
        subset=["beach_id", "forecast_date", "forecast_generated_at"], keep="first"
    )
    combined.to_parquet(history_path, index=False)
    dates = pd.to_datetime(combined["forecast_date"], errors="coerce")
    print(
        f"Wrote {len(combined)} rows ({combined['beach_id'].nunique()} beaches, "
        f"{dates.min().date()} -> {dates.max().date()}, {skipped} commits skipped) "
        f"to {history_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
