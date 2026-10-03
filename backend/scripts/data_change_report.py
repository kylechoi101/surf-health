"""Side-by-side data-change table for curated snapshots (UPDATE_PLAN step 1.6).

    python scripts/data_change_report.py --forecast-date 2026-10-02 \
        ci=../data/snapshots/ci-2026-10-02 before=../data/snapshots/before-2026-10-02 \
        after=../data/snapshots/after-2026-10-02

Each argument is label=folder. Every figure is computed the same way for every folder, so a
column built by CI (what is actually served) can sit next to locally built ones.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from app.data.pipeline.exceedance import is_pcr_measurement

COUNTIES = ["Orange", "Monterey", "San Diego", "Los Angeles", "San Francisco", "Santa Barbara"]


def _labels_last_365(obs: pd.DataFrame, since: pd.Timestamp) -> pd.DataFrame:
    """One row per enterococcus beach-day: worst sample's label and assay."""
    e = obs[obs["analyte"].str.contains("enterococcus", case=False, na=False)].copy()
    e["day"] = pd.to_datetime(e["sample_time"]).dt.normalize()
    e = e[e["day"] >= since]
    e["pcr"] = is_pcr_measurement(e["method"], e["units"])
    e["_v"] = pd.to_numeric(e["value"], errors="coerce")
    e = e.sort_values(["exceeds_stv", "_v"]).groupby(["beach_id", "day"]).tail(1)
    return e


def column(folder: Path, forecast_date: pd.Timestamp) -> dict[str, object]:
    obs = pd.read_parquet(folder / "observations.parquet")
    beach_day = pd.read_parquet(folder / "beach_day.parquet", columns=["beach_id"])
    beaches = pd.read_parquet(folder / "beaches.parquet")
    fc = pd.read_parquet(folder / "forecasts.parquet")
    labels = _labels_last_365(obs, forecast_date - pd.Timedelta(days=365))
    pos = labels[labels["exceeds_stv"].astype(bool)]

    served = fc.merge(beaches[["beach_id", "county", "support_status", "latest_official_sample_at"]],
                      on="beach_id", how="left", suffixes=("", "_b"))
    county = served["county_b"] if "county_b" in served else served["county"]
    prod = served["support_status"] == "production"
    age = (forecast_date - pd.to_datetime(served["latest_official_sample_at"]).dt.tz_localize(None)
           .dt.normalize()).dt.days

    report = json.loads((folder / "county_advisories_report.json").read_text())
    gate = json.loads((folder / "system_health.json").read_text()).get("scraper_gate") or {}
    by_county = county.value_counts()
    return {
        "observations rows": len(obs),
        "beach_day rows": len(beach_day),
        "enterococcus beach-days, last 365 d": len(labels),
        "positive labels, last 365 d (culture / ddPCR)":
            f"{int((~pos['pcr']).sum())} / {int(pos['pcr'].sum())}",
        "beaches served (production)": f"{len(served)} ({int(prod.sum())})",
        **{f"served: {c}": int(by_county.get(c, 0)) for c in COUNTIES},
        "median sample age of served beaches (d)": float(age.median()),
        "advisories resolved": report.get("total_resolved_advisories"),
        "unresolved (unexpected / total)":
            f"{gate.get('unresolved_unexpected')} / {gate.get('unresolved_total')}",
        "county scrapers with an error": sorted(
            c["county"] for c in report.get("counties", [])
            if c.get("error") and not _is_known_gap(c)),
        "known gaps (no public source)": sorted(
            c["county"] for c in report.get("counties", []) if _is_known_gap(c)),
    }


def _is_known_gap(county_report: dict) -> bool:
    """A county with no public source is a known gap, not a scraper breakage.

    Newer reports carry ``no_public_source``; a report written before that field
    existed carries the same reason in ``error``.
    """
    if county_report.get("no_public_source"):
        return True
    return str(county_report.get("error") or "").startswith("no public posting source")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forecast-date", required=True)
    ap.add_argument("snapshots", nargs="+", help="label=folder")
    args = ap.parse_args()
    day = pd.Timestamp(args.forecast_date)
    cols = {}
    for spec in args.snapshots:
        label, folder = spec.split("=", 1)
        cols[label] = column(Path(folder), day)
    table = pd.DataFrame(cols)
    print("| | " + " | ".join(table.columns) + " |")
    print("|---" * (len(table.columns) + 1) + "|")
    for metric, row in table.iterrows():
        print(f"| {metric} | " + " | ".join(str(v) for v in row) + " |")


if __name__ == "__main__":
    main()
