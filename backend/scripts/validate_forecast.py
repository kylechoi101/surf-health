"""Sanity-check the served forecast before it is committed/deployed.

Run AFTER the ML training/forecast step and BEFORE the git-commit step in
``.github/workflows/daily-forecast.yml``. A failed training run can leave a
stale ``forecasts.parquet`` on disk (or write a degenerate one); without this
gate the workflow would happily commit it and the API would serve stale/garbage
risk bands with no alarm. This script exits non-zero on any of the failure
conditions below so the workflow aborts before committing.

Usage:
  python scripts/validate_forecast.py --curated ../data/curated/

Failure conditions (exit 1):
  - forecasts.parquet missing or unparseable.
  - row count is zero, or far below the prior committed run
    (< MIN_PROW_FRACTION of the prior count) — a partial/truncated write.
  - row count below MIN_ABSOLUTE_ROWS — too few beaches to be a real run.
  - any served probability (p_exceed) is NaN/inf or outside [0, 1].
  - ALL served probabilities are identical (degenerate model / constant output).
  - the forecast date stamp is older than today in America/Los_Angeles
    (stale forecast — training did not produce a fresh date).

The prior-run row count is read from the version committed at git HEAD
(``git show HEAD:<path>``). When that is unavailable (first run, shallow
checkout, file not yet tracked) the relative-drop check is skipped and only
the absolute floor applies — we never block on a missing baseline.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# --- Thresholds (documented, deliberately conservative) ----------------------
# Absolute minimum number of forecast rows. A healthy run covers ~200+ beaches
# (210 at time of writing); anything under this floor is a broken/partial run,
# not a real refresh. Kept well below the live count so a legitimate roster
# shrink does not false-trip the gate.
MIN_ABSOLUTE_ROWS = 50
# Reject when the new run drops below this fraction of the prior committed run.
# 0.80 tolerates normal day-to-day roster churn (beaches dropping out of the
# 45-day recency window) while catching a truncated/partial write.
MIN_PROW_FRACTION = 0.80
# Probability column the API serves and the apps band on.
_PROB_COLUMN = "p_exceed"
_DATE_COLUMN = "forecast_date"
_FORECAST_FILE = "forecasts.parquet"
_PT = ZoneInfo("America/Los_Angeles")


def _prior_committed_row_count(forecast_path: Path) -> int | None:
    """Row count of the forecast committed at git HEAD, or None if unavailable.

    Used only for the relative-drop check; a missing baseline (first run,
    shallow checkout, untracked file) is treated as "no baseline" rather than
    a failure.
    """
    try:
        repo_root = Path(
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=forecast_path.parent,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        rel = forecast_path.resolve().relative_to(repo_root)
        blob = subprocess.run(
            ["git", "show", f"HEAD:{rel.as_posix()}"],
            cwd=repo_root,
            capture_output=True,
            check=True,
        ).stdout
        if not blob:
            return None
        return int(len(pd.read_parquet(io.BytesIO(blob))))
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def validate(curated_dir: Path) -> list[str]:
    """Return a list of failure messages (empty list == pass)."""
    failures: list[str] = []
    forecast_path = curated_dir / _FORECAST_FILE

    if not forecast_path.exists():
        return [f"{_FORECAST_FILE} is missing at {forecast_path}."]
    try:
        forecasts = pd.read_parquet(forecast_path)
    except Exception as exc:  # noqa: BLE001 — any read failure is a hard fail
        return [f"{_FORECAST_FILE} is unparseable: {exc!r}."]

    rows = len(forecasts)
    if rows == 0:
        return [f"{_FORECAST_FILE} has zero rows."]
    if rows < MIN_ABSOLUTE_ROWS:
        failures.append(
            f"Row count {rows} is below the absolute floor {MIN_ABSOLUTE_ROWS} "
            "— partial/broken run."
        )
    prior_rows = _prior_committed_row_count(forecast_path)
    if prior_rows is not None and prior_rows > 0:
        if rows < MIN_PROW_FRACTION * prior_rows:
            failures.append(
                f"Row count {rows} dropped below {MIN_PROW_FRACTION:.0%} of the "
                f"prior committed run ({prior_rows}) — likely a truncated write."
            )

    if _PROB_COLUMN not in forecasts.columns:
        failures.append(f"Served probability column '{_PROB_COLUMN}' is missing.")
    else:
        probs = pd.to_numeric(forecasts[_PROB_COLUMN], errors="coerce").to_numpy(dtype=float)
        # np.isfinite is False for both NaN and +/-inf.
        finite_mask = np.isfinite(probs)
        n_nonfinite = int((~finite_mask).sum())
        if n_nonfinite:
            failures.append(
                f"{n_nonfinite} served '{_PROB_COLUMN}' value(s) are NaN/inf."
            )
        finite = probs[finite_mask]
        if len(finite):
            out_of_range = int(((finite < 0.0) | (finite > 1.0)).sum())
            if out_of_range:
                failures.append(
                    f"{out_of_range} served '{_PROB_COLUMN}' value(s) are outside [0, 1] "
                    f"(min={finite.min():.4f}, max={finite.max():.4f})."
                )
            # Degenerate model: every served probability identical means the
            # model collapsed to a constant — useless and a sign of a bad fit.
            if rows > 1 and np.unique(finite).size == 1:
                failures.append(
                    f"All served '{_PROB_COLUMN}' values are identical "
                    f"({float(finite[0]):.4f}) — degenerate model output."
                )

    if _DATE_COLUMN not in forecasts.columns:
        failures.append(f"Forecast date column '{_DATE_COLUMN}' is missing.")
    else:
        stamped = pd.to_datetime(forecasts[_DATE_COLUMN], errors="coerce").dropna()
        if stamped.empty:
            failures.append(f"Forecast date column '{_DATE_COLUMN}' has no parseable dates.")
        else:
            newest = stamped.max().date()
            today_pt = datetime.now(_PT).date()
            if newest < today_pt:
                failures.append(
                    f"Forecast date {newest.isoformat()} is older than today "
                    f"({today_pt.isoformat()} PT) — stale forecast."
                )

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--curated",
        type=Path,
        default=Path("../data/curated/"),
        help="Path to the curated data directory containing forecasts.parquet.",
    )
    args = parser.parse_args(argv)

    failures = validate(args.curated)
    if failures:
        print("FAIL: forecast validation failed:", file=sys.stderr)
        for message in failures:
            print(f"  - {message}", file=sys.stderr)
        return 1

    # Concise pass summary.
    forecasts = pd.read_parquet(args.curated / _FORECAST_FILE)
    probs = pd.to_numeric(forecasts[_PROB_COLUMN], errors="coerce")
    newest = pd.to_datetime(forecasts[_DATE_COLUMN], errors="coerce").max()
    print(
        f"PASS: {len(forecasts)} rows, forecast_date={newest.date().isoformat()}, "
        f"p_exceed range [{probs.min():.4f}, {probs.max():.4f}] "
        f"({probs.nunique()} distinct)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
