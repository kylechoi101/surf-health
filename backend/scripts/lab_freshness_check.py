"""Check enterococcus lab-result freshness per county from observations.parquet.

Eligible counties: >= 20 distinct sample dates in trailing 365 days.
cadence_days = median gap between consecutive distinct county-wide sample dates (trailing 180 days).
age_days = today - newest sample date.
stale if age_days > max(14, 3 * cadence_days).

Writes system_health.json["lab_freshness"] (merged into existing file).
Prints a formatted table. Exits 0 always.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from app.core.json_safe import dumps_strict


def compute_lab_freshness(
    observations_df: pd.DataFrame,
    today: date,
) -> list[dict]:
    """Compute per-county lab freshness from observations dataframe.

    Filters for enterococcus only (case-insensitive).
    Returns list of dicts with county, eligible, newest, age_days, cadence_days, stale, reason.
    """
    if observations_df.empty:
        return []

    df = observations_df.copy()
    if "analyte" in df.columns:
        df = df[df["analyte"].astype(str).str.lower() == "enterococcus"]
    if df.empty or "county" not in df.columns or "sample_date" not in df.columns:
        return []

    # Ensure sample_date is date objects
    df["sample_date"] = pd.to_datetime(df["sample_date"], errors="coerce").dt.date
    df = df[df["sample_date"].notna()]
    if df.empty:
        return []

    cutoff_365 = today - timedelta(days=365)
    cutoff_180 = today - timedelta(days=180)

    results: list[dict] = []
    # Sort counties alphabetically
    counties = sorted(df["county"].dropna().unique())

    for county in counties:
        cdf = df[df["county"] == county]

        # Distinct sample dates in trailing 365 days (inclusive: cutoff_365 <= d <= today)
        dates_365 = sorted(set(cdf[(cdf["sample_date"] >= cutoff_365) & (cdf["sample_date"] <= today)]["sample_date"]))
        n_dates_365 = len(dates_365)
        eligible = n_dates_365 >= 20

        # Newest sample date <= today (ignore future-dated samples if any)
        past_dates = sorted(set(cdf[cdf["sample_date"] <= today]["sample_date"]))
        if not past_dates:
            # All samples future-dated or no samples on or before today
            all_dates = sorted(set(cdf["sample_date"]))
            newest = all_dates[-1] if all_dates else None
            age_days = (today - newest).days if newest else None
        else:
            newest = past_dates[-1]
            age_days = (today - newest).days

        # Distinct sample dates in trailing 180 days (inclusive)
        dates_180 = sorted(set(cdf[(cdf["sample_date"] >= cutoff_180) & (cdf["sample_date"] <= today)]["sample_date"]))
        if len(dates_180) >= 2:
            gaps = [(dates_180[i + 1] - dates_180[i]).days for i in range(len(dates_180) - 1)]
            cadence_days = float(np.median(gaps))
        else:
            cadence_days = None

        stale = False
        if not eligible:
            reason = f"ineligible (<20 sample dates in trailing 365d: {n_dates_365})"
        else:
            threshold = max(14.0, 3.0 * cadence_days) if cadence_days is not None else 14.0
            if age_days is not None and age_days > threshold:
                stale = True
                cadence_str = f"{cadence_days:.1f}d" if cadence_days is not None else "None"
                reason = f"stale: age {age_days}d > max(14, 3 * {cadence_str}) = {threshold:.0f}d"
            else:
                cadence_str = f"{cadence_days:.1f}d" if cadence_days is not None else "None"
                reason = f"fresh: age {age_days}d <= max(14, 3 * {cadence_str}) = {threshold:.0f}d"

        results.append({
            "county": str(county),
            "eligible": bool(eligible),
            "newest": str(newest) if newest else None,
            "age_days": int(age_days) if age_days is not None else None,
            "cadence_days": float(cadence_days) if cadence_days is not None else None,
            "stale": bool(stale),
            "reason": reason,
        })

    return results


def format_freshness_table(results: list[dict]) -> str:
    """Format results as an ASCII text table."""
    headers = ["County", "Newest", "Age", "Cadence", "Stale", "Reason"]
    rows = []
    for r in results:
        age_str = f"{r['age_days']}d" if r['age_days'] is not None else "-"
        cad_str = f"{r['cadence_days']:.1f}d" if r['cadence_days'] is not None else "-"
        stale_str = "YES" if r["stale"] else "no"
        rows.append([
            r["county"],
            r["newest"] or "-",
            age_str,
            cad_str,
            stale_str,
            r["reason"],
        ])

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(val))

    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    sep_line = "  ".join("-" * col_widths[i] for i in range(len(headers)))
    row_lines = ["  ".join(val.ljust(col_widths[i]) for i, val in enumerate(row)) for row in rows]

    return "\n".join([header_line, sep_line, *row_lines])


def update_system_health(
    curated_dir: Path,
    freshness_payload: dict,
) -> None:
    """Merge lab_freshness into system_health.json preserving all other keys."""
    health_file = curated_dir / "system_health.json"
    if health_file.exists():
        try:
            health_data = json.loads(health_file.read_text())
        except Exception:
            health_data = {}
    else:
        health_data = {}

    health_data["lab_freshness"] = freshness_payload
    health_file.write_text(dumps_strict(health_data))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check per-county lab-result freshness from observations.parquet")
    parser.add_argument("--curated", required=True, type=Path, help="Path to curated data directory")
    parser.add_argument("--today", type=str, default=None, help="Evaluation date (YYYY-MM-DD), default UTC today")
    parser.add_argument("--json-out", type=Path, default=None, help="Optional output JSON path")
    args = parser.parse_args()

    if args.today:
        today = datetime.strptime(args.today, "%Y-%m-%d").date()
    else:
        today = datetime.now(timezone.utc).date()

    obs_path = args.curated / "observations.parquet"
    if not obs_path.exists():
        print(f"observations.parquet not found in {args.curated}", file=sys.stderr)
        results = []
    else:
        try:
            obs_df = pd.read_parquet(obs_path)
            results = compute_lab_freshness(obs_df, today)
        except Exception as e:
            print(f"Error reading observations.parquet: {e}", file=sys.stderr)
            results = []

    stale_count = sum(1 for r in results if r["stale"])
    freshness_payload = {
        "as_of": today.isoformat(),
        "stale_count": stale_count,
        "counties": results,
    }

    # Print table
    if results:
        print(format_freshness_table(results))
        print(f"\n{stale_count} stale county feed(s) flagged.")
    else:
        print("No county observations analyzed.")

    # Write system_health.json
    try:
        update_system_health(args.curated, freshness_payload)
    except Exception as e:
        print(f"Warning: failed to update system_health.json: {e}", file=sys.stderr)

    # Optional json-out
    if args.json_out:
        try:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(dumps_strict(freshness_payload))
        except Exception as e:
            print(f"Warning: failed to write {args.json_out}: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
