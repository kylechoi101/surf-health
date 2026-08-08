#!/usr/bin/env python
"""Step 4 rebuild driver: regenerate beach_day from observations, covariates held fixed.

Two stages, run separately so their diffs cannot be confounded (Step 3 § 8):

  stage A  --observations ../data/curated/observations.parquet
           rebuild the label frame from the observations already on disk.
           Expected diff vs the shipped frame: the four assay columns appear,
           nothing else moves.

  stage B  --observations <full-rebuild output>/observations.parquet
           rebuild from a fully re-normalized observations frame. All remaining
           movement is source vintage.

Why not just run `python -m app.data.pipeline.cli` with every covariate flag?
Because ~9 of the 83 beach_day columns come from live network fetches (CDIP
waves, ERDDAP salinity/temperature) whose values move every run. Any of those
moving by a millimetre would land in the same diff as the relabel and make the
attribution impossible. So this driver:

  * rebuilds what ``build_beach_day_frame`` produces (the label half),
  * RE-DERIVES every covariate block that is a deterministic function of an
    on-disk artifact -- hydrology/precip, solar-wind/marine-microbiology,
    stormwater + rain policy -- using the same functions cli.py calls, so rows
    the rebuild ADDS get real feature values instead of nulls,
  * and re-attaches only the network-derived columns verbatim, keyed on
    (beach_id, sample_date).

The re-derived blocks are checked against the covariate source on shared rows;
any disagreement is printed, because it would mean the pipeline's join is not
reproducible from disk.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from app.data.pipeline.beachwatch import build_beach_day_frame
from app.data.pipeline.cli import _backfill_beach_links
from app.data.pipeline.hydrology import build_beach_hydrology_daily
from app.data.pipeline.marine_microbiology import (
    build_marine_microbiology_daily,
    compute_beach_coastal_features,
    compute_beach_shore_azimuth,
)
from app.data.pipeline.solar_wind import explode_solar_wind_to_beaches
from app.data.pipeline.stormwater import apply_stormwater_features

# Columns that only a live fetch can produce. Everything else is re-derived.
NETWORK_ONLY_COLUMNS = [
    "cdip_station_id",
    "cdip_distance_km",
    "wave_height_m",
    "dominant_period_s",
    "wave_direction_deg",
    "erddap_source_name",
    "erddap_distance_km",
    "salinity_psu",
    "water_temperature_c",
]

STREAMFLOW_ZERO_FILL = [
    "streamflow_cfs_latest",
    "streamflow_cfs_mean_24h",
    "streamflow_cfs_max_24h",
    "streamflow_rising_flag",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curated", type=Path, required=True, help="dir holding the daily caches")
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--stations", type=Path, default=None)
    parser.add_argument("--advisories", type=Path, required=True)
    parser.add_argument("--covariate-source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    curated: Path = args.curated
    observations = pd.read_parquet(args.observations)
    stations = pd.read_parquet(args.stations or curated / "beaches.parquet")
    advisories = pd.read_parquet(args.advisories)
    source = pd.read_parquet(args.covariate_source)
    source["sample_date"] = pd.to_datetime(source["sample_date"])

    print(f"observations : {len(observations):>8,} rows  {args.observations}")
    print(f"stations     : {len(stations):>8,} rows  {args.stations}")
    print(f"advisories   : {len(advisories):>8,} rows")
    print(f"covariates   : {len(source):>8,} rows x {source.shape[1]} cols")

    bd = build_beach_day_frame(observations, stations, advisories)
    bd["sample_date"] = pd.to_datetime(bd["sample_date"])
    print(f"rebuilt base : {len(bd):>8,} rows x {bd.shape[1]} cols")

    report: dict = {
        "observations": str(args.observations),
        "observation_rows": int(len(observations)),
        "base_rows": int(len(bd)),
    }

    # ---------------------------------------------------------------- network
    net = [c for c in NETWORK_ONLY_COLUMNS if c in source.columns]
    net_static = source.groupby("beach_id", as_index=False)[
        [c for c in net if source.groupby("beach_id")[c].nunique(dropna=False).max() <= 1]
    ].first()
    net_varying = [c for c in net if c not in net_static.columns]
    bd = bd.merge(net_static, on="beach_id", how="left")
    if net_varying:
        bd = bd.merge(
            source[["beach_id", "sample_date", *net_varying]].drop_duplicates(
                ["beach_id", "sample_date"], keep="last"
            ),
            on=["beach_id", "sample_date"],
            how="left",
        )
    print(f"network columns re-attached: static={list(net_static.columns[1:])} varying={net_varying}")

    # ------------------------------------------------------------- hydrology
    links = pd.read_parquet(curated / "hydrologic_beach_links.parquet")
    links = _backfill_beach_links(links, stations)
    streamflow = pd.read_parquet(curated / "streamflow_daily.parquet")
    precip = pd.read_parquet(curated / "precip_daily.parquet")
    hydro = build_beach_hydrology_daily(links, streamflow, precip)
    hydro["sample_date"] = pd.to_datetime(hydro["sample_date"])
    bd = bd.merge(hydro, on=["beach_id", "sample_date"], how="left")
    print(f"hydrology joined: {len(hydro):,} rows")

    # ------------------------------------------------------- solar/marine mb
    shore_az = compute_beach_shore_azimuth(stations)
    coastal = compute_beach_coastal_features(stations)
    sw = pd.read_parquet(curated / "solar_wind_daily.parquet")
    sw["sample_date"] = pd.to_datetime(sw["sample_date"])
    beach_sw = explode_solar_wind_to_beaches(sw, stations)
    mm = build_marine_microbiology_daily(beach_sw, shore_az)
    mm["sample_date"] = pd.to_datetime(mm["sample_date"])
    bd = bd.merge(mm, on=["beach_id", "sample_date"], how="left")
    bd = bd.merge(coastal, on="beach_id", how="left")
    print(f"marine-microbiology joined: {len(mm):,} rows")

    # ---------------------------------------------------------- cli fixups
    for col in STREAMFLOW_ZERO_FILL:
        if col in bd.columns:
            bd[col] = bd[col].fillna(0.0)

    # ------------------------------------------------- stormwater + rain policy
    storm = pd.read_parquet(curated / "stormwater_beach_features.parquet")
    bd = apply_stormwater_features(bd, storm)
    print(f"stormwater features joined: {len(storm):,} beaches")

    # ------------------------------------------------------------- ordering
    ordered = [c for c in source.columns if c in bd.columns]
    ordered += [c for c in bd.columns if c not in ordered]
    bd = bd[ordered]

    # ------------------------------------------------- reproducibility check
    key = ["beach_id", "sample_date"]
    a = source.set_index(key).sort_index()
    b = bd.set_index(key).sort_index()
    shared = a.index.intersection(b.index)
    report["keys_added"] = int(len(b.index.difference(a.index)))
    report["keys_removed"] = int(len(a.index.difference(b.index)))
    print(f"key delta: +{report['keys_added']:,} added, -{report['keys_removed']:,} removed")

    mismatches: dict[str, int] = {}
    for col in a.columns:
        if col not in b.columns:
            continue
        so, sn = a.loc[shared, col], b.loc[shared, col]
        try:
            if pd.api.types.is_numeric_dtype(so) and pd.api.types.is_numeric_dtype(sn):
                diff = ~((so == sn) | (so.isna() & sn.isna()))
            else:
                diff = so.astype(object).where(so.notna(), "<NA>") != sn.astype(object).where(
                    sn.notna(), "<NA>"
                )
        except Exception as exc:  # noqa: BLE001
            print(f"  compare failed {col}: {exc}")
            continue
        if int(diff.sum()):
            mismatches[col] = int(diff.sum())
    report["shared_rows"] = int(len(shared))
    report["columns_changed_on_shared_rows"] = mismatches
    print(f"\nshared rows: {len(shared):,}")
    if mismatches:
        print("columns that changed on shared rows:")
        for col, n in sorted(mismatches.items(), key=lambda kv: -kv[1]):
            tag = "network-attached" if col in net else "re-derived/label"
            print(f"  {col:<36} {n:>9,}  {tag}")
    else:
        print("no column changed on shared rows")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    bd.to_parquet(args.out, index=False)
    print(f"\nwrote {args.out}  ({len(bd):,} rows x {bd.shape[1]} cols)")
    report["out_rows"] = int(len(bd))
    report["out_cols"] = int(bd.shape[1])
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
