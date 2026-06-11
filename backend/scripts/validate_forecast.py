"""Sanity-check the served forecast before it is committed/deployed.

Run AFTER the ML training/forecast step and BEFORE the git-commit step in
``.github/workflows/daily-forecast.yml``. A failed training run can leave a
stale ``forecasts.parquet`` on disk (or write a degenerate one); without this
gate the workflow would happily commit it and the API would serve stale/garbage
risk bands with no alarm. This script exits non-zero on any of the failure
conditions below so the workflow aborts before committing.

Usage:
  python scripts/validate_forecast.py --curated ../data/curated/ \
      [--previous /tmp/prev_forecasts.parquet]

Failure conditions (exit 1):
  - forecasts.parquet missing or unparseable.
  - row count is zero, or far below the prior committed run
    (< MIN_PROW_FRACTION of the prior count) — a partial/truncated write.
  - row count below MIN_ABSOLUTE_ROWS — too few beaches to be a real run.
  - any served probability (p_exceed) is NaN/inf or outside [0, 1].
  - ALL served probabilities are identical (degenerate model / constant output).
  - the forecast date stamp is older than today in America/Los_Angeles
    (stale forecast — training did not produce a fresh date). EXCEPTION: when
    THIS run's system_health.json records that --enforce-release-gate
    deliberately blocked publication (release_gate.enforced true,
    forecast_published false, pipeline_freshness today PT), the frozen
    last-validated forecast is EXPECTED — the check prints a notice instead of
    failing, so the run still commits the blockers for audit and the
    verify_release_gate.py step (after the commit) is what fails the job.

Anomaly checks (exit 1; added 2026-06-11 — see ``anomaly_failures``):
  - all-safe collapse: EVERY p_exceed sits below the Low band threshold.
  - distribution shift vs the run passed via ``--previous`` (skipped
    gracefully when that file is absent/unreadable): mean p_exceed shifted
    more than 4x in either direction, or row count below 50% of the prior run.
  - band sanity: the non-Low band count collapsed to zero while the prior run
    served >= MIN_PREVIOUS_NON_LOW non-Low rows.

``SKIP_FORECAST_ANOMALY_CHECKS=1`` bypasses ONLY the anomaly checks (escape
hatch for a deliberate model/calibration change) and prints a loud notice;
the shape/freshness checks above always run.

The prior-run row count is read from the version committed at git HEAD
(``git show HEAD:<path>``). When that is unavailable (first run, shallow
checkout, file not yet tracked) the relative-drop check is skipped and only
the absolute floor applies — we never block on a missing baseline.
"""

from __future__ import annotations

import argparse
import io
import json
import os
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
_BAND_COLUMN = "risk_band"
_FORECAST_FILE = "forecasts.parquet"
_PT = ZoneInfo("America/Los_Angeles")

# --- Anomaly-gate thresholds (checks added 2026-06-11) ------------------------
# Distribution-shift bounds vs the previous run's mean p_exceed. A dependency
# or calibration regression squashes/explodes the whole probability field at
# once; legitimate day-to-day drift stays well inside a 4x band either way.
MEAN_SHIFT_LOWER_RATIO = 0.25
MEAN_SHIFT_UPPER_RATIO = 4.0
# Reject when the new run carries fewer than this fraction of the previous
# run's rows (looser than MIN_PROW_FRACTION because the --previous artifact
# may be older than git HEAD).
PREVIOUS_ROW_FRACTION = 0.50
# The previous run must have served at least this many non-Low rows for the
# band-sanity check to apply — avoids tripping off an already-degenerate
# baseline. The live mix is ~28 non-Low of 211 rows.
MIN_PREVIOUS_NON_LOW = 5
# Escape hatch for a deliberate model/calibration change; bypasses ONLY the
# anomaly checks, never the shape/freshness checks.
_SKIP_ENV = "SKIP_FORECAST_ANOMALY_CHECKS"


def _low_band_threshold() -> float:
    """Low/Moderate cutpoint, read from the canonical banding module so this
    gate cannot silently drift when the cutpoints are re-tuned."""
    try:
        from app.ml.calibration import _LOW_THRESHOLD

        return float(_LOW_THRESHOLD)
    except Exception:  # noqa: BLE001 — fall back when app deps are unavailable
        # Mirrors app/ml/calibration.py _LOW_THRESHOLD at time of writing.
        return 0.20


def _finite_probs(frame: pd.DataFrame) -> np.ndarray:
    """Finite served probabilities; empty array when the column is absent."""
    if _PROB_COLUMN not in frame.columns:
        return np.array([], dtype=float)
    probs = pd.to_numeric(frame[_PROB_COLUMN], errors="coerce").to_numpy(dtype=float)
    return probs[np.isfinite(probs)]


def _release_gate_blocked_today(curated_dir: Path, today_pt) -> bool:
    """True iff THIS run's training step deliberately skipped publication.

    Only a FRESH system_health.json (pipeline_freshness today in PT) whose
    release_gate block says enforced-and-not-published excuses a stale
    forecast date. An old payload — e.g. left by a training step that crashed
    before writing health — must never mask a genuinely stale forecast, so
    every parse failure here returns False (the stale check then fails as
    usual: fail-closed).
    """
    try:
        payload = json.loads((curated_dir / "system_health.json").read_text())
    except (OSError, json.JSONDecodeError):
        return False
    gate = payload.get("release_gate")
    if not isinstance(gate, dict):
        return False
    if not gate.get("enforced") or gate.get("forecast_published", True):
        return False
    try:
        stamp = pd.Timestamp(payload.get("pipeline_freshness"))
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        return stamp.tz_convert(_PT).date() >= today_pt
    except (TypeError, ValueError):
        return False


def _non_low_count(frame: pd.DataFrame, low_threshold: float) -> int:
    """Rows served with a band other than Low.

    Prefers the served ``risk_band`` column (catches banding bugs even when
    the probabilities look healthy); falls back to thresholding p_exceed.
    """
    if _BAND_COLUMN in frame.columns:
        bands = frame[_BAND_COLUMN]
        return int((bands.notna() & (bands.astype(str) != "Low")).sum())
    return int((_finite_probs(frame) >= low_threshold).sum())


def _load_previous(previous_path: Path | None) -> pd.DataFrame | None:
    """Previous run's forecast frame, or None when unavailable.

    The comparison checks are best-effort: a missing/unreadable baseline
    (first run, expired CI artifact) skips them rather than blocking,
    mirroring the git-HEAD baseline handling in ``_prior_committed_row_count``.
    """
    if previous_path is None:
        return None
    if not previous_path.exists():
        print(
            f"NOTE: previous forecast not found at {previous_path}; "
            "skipping distribution-shift and band-sanity checks.",
            file=sys.stderr,
        )
        return None
    try:
        previous = pd.read_parquet(previous_path)
    except Exception as exc:  # noqa: BLE001 — any read failure means no baseline
        print(
            f"NOTE: previous forecast at {previous_path} is unparseable ({exc!r}); "
            "skipping distribution-shift and band-sanity checks.",
            file=sys.stderr,
        )
        return None
    if previous.empty:
        print(
            f"NOTE: previous forecast at {previous_path} has zero rows; "
            "skipping distribution-shift and band-sanity checks.",
            file=sys.stderr,
        )
        return None
    return previous


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
                if _release_gate_blocked_today(curated_dir, today_pt):
                    print(
                        f"NOTICE: forecast date {newest.isoformat()} is older than "
                        f"today ({today_pt.isoformat()} PT) but this run's release "
                        "gate deliberately blocked publication — the last-validated "
                        "forecast keeps serving. Not a validation failure; "
                        "verify_release_gate.py fails the job after the commit.",
                        file=sys.stderr,
                    )
                else:
                    failures.append(
                        f"Forecast date {newest.isoformat()} is older than today "
                        f"({today_pt.isoformat()} PT) — stale forecast."
                    )

    return failures


def anomaly_failures(curated_dir: Path, previous_path: Path | None) -> list[str]:
    """Anomaly checks (2026-06-11). Return failure messages (empty == pass).

    These run AFTER ``validate``'s shape/freshness checks and close the gap
    they leave open: a dependency-induced calibration squash that keeps
    distinct, in-range, full-row-count probabilities but collapses every
    beach to Low passed every check above and silently under-warned.
    """
    forecast_path = curated_dir / _FORECAST_FILE
    try:
        forecasts = pd.read_parquet(forecast_path)
    except Exception:  # noqa: BLE001 — missing/unparseable already hard-fails in validate()
        return []
    if forecasts.empty:
        return []

    failures: list[str] = []
    low_threshold = _low_band_threshold()
    probs = _finite_probs(forecasts)
    rows = len(forecasts)

    # (1) All-safe collapse. Several Tijuana-plume stations (Imperial Beach
    # area) run ~0.85 exceedance base rates and are essentially never
    # legitimately Low, so a day where EVERY beach forecasts below the Low
    # threshold means a calibration/feature collapse, not clean water
    # statewide. (~87% of beaches below the threshold is normal; 100% is not.)
    if len(probs) and float(probs.max()) < low_threshold:
        failures.append(
            f"[all-safe-collapse] every served '{_PROB_COLUMN}' value is below the "
            f"Low band threshold {low_threshold:.2f} "
            f"(max={float(probs.max()):.4f} over {len(probs)} rows) — implausible "
            "given chronically contaminated stations."
        )

    previous = _load_previous(previous_path)
    if previous is None:
        return failures
    prev_rows = len(previous)
    prev_probs = _finite_probs(previous)

    # (2) Distribution shift vs the previous run.
    if rows < PREVIOUS_ROW_FRACTION * prev_rows:
        failures.append(
            f"[distribution-shift] row count {rows} is below "
            f"{PREVIOUS_ROW_FRACTION:.0%} of the previous run's {prev_rows}."
        )
    if len(probs) and len(prev_probs):
        mean = float(probs.mean())
        prev_mean = float(prev_probs.mean())
        if mean < MEAN_SHIFT_LOWER_RATIO * prev_mean:
            failures.append(
                f"[distribution-shift] mean '{_PROB_COLUMN}' {mean:.4f} is below "
                f"{MEAN_SHIFT_LOWER_RATIO}x the previous run's mean {prev_mean:.4f} "
                f"(rows {rows} vs {prev_rows}) — probability squash."
            )
        if mean > MEAN_SHIFT_UPPER_RATIO * prev_mean:
            failures.append(
                f"[distribution-shift] mean '{_PROB_COLUMN}' {mean:.4f} is above "
                f"{MEAN_SHIFT_UPPER_RATIO}x the previous run's mean {prev_mean:.4f} "
                f"(rows {rows} vs {prev_rows}) — probability explosion."
            )

    # (3) Band sanity: the served band column collapsing to all-Low while the
    # previous run had a real non-Low population catches a banding/display
    # regression even when the raw probabilities still look healthy.
    non_low = _non_low_count(forecasts, low_threshold)
    prev_non_low = _non_low_count(previous, low_threshold)
    if non_low == 0 and prev_non_low >= MIN_PREVIOUS_NON_LOW:
        failures.append(
            f"[band-sanity] current run serves 0 non-Low rows while the previous "
            f"run served {prev_non_low} (>= {MIN_PREVIOUS_NON_LOW}) — band collapse."
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
    parser.add_argument(
        "--previous",
        type=Path,
        default=None,
        help="Prior run's forecasts.parquet for the distribution-shift and "
        "band-sanity checks; skipped gracefully when the file is absent.",
    )
    args = parser.parse_args(argv)

    failures = validate(args.curated)
    if os.environ.get(_SKIP_ENV) == "1":
        print(
            "=" * 78
            + f"\nNOTICE: {_SKIP_ENV}=1 — BYPASSING the forecast anomaly checks"
            "\n(all-safe-collapse, distribution-shift, band-sanity)."
            "\nOnly valid for a deliberate model/calibration change; unset it after."
            "\n" + "=" * 78,
            file=sys.stderr,
        )
    else:
        failures.extend(anomaly_failures(args.curated, args.previous))
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
