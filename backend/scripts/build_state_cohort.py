"""Build a full-feature beach_day for one WQP state cohort (e.g. Texas), into an
ISOLATED output dir so the production curated data / model registry are never
touched. Enriches with hydrology (USGS + Open-Meteo precip), marine-micro
(Open-Meteo solar/wind), and historical ocean (Open-Meteo Marine -> the non-CA
CDIP replacement). For the compare-and-contrast experiment.

    python scripts/build_state_cohort.py --state US:48 --start 2023-01-01 \
        --end 2026-06-30 --out ../data/cohorts/tx
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
from pathlib import Path

import pandas as pd

from app.core.config import get_settings
from app.data.connectors.hydrology_sources import (
    OpenMeteoHistoricalPrecipConnector,
    OpenMeteoHistoricalSolarWindConnector,
    OpenMeteoMarineHistoricalConnector,
    UsgsNwisConnector,
    aggregate_marine_history_daily,
)
from app.data.pipeline.beachwatch import build_beach_day_frame
from app.data.pipeline.external_covariates import haversine_km
from app.data.pipeline.hydrography import build_hydrologic_beach_links
from app.data.pipeline.hydrology import aggregate_streamflow_windows, build_beach_hydrology_daily
from app.data.pipeline.marine_microbiology import (
    build_marine_microbiology_daily,
    compute_beach_coastal_features,
    compute_beach_shore_azimuth,
)
from app.data.pipeline.precipitation import aggregate_precip_windows
from app.data.pipeline.solar_wind import aggregate_solar_wind_windows
from app.data.pipeline.wqp import (
    build_wqp_stations,
    fetch_national_wqp,
    to_beach_day_observations,
)


def _explode_daily_to_beaches(daily: pd.DataFrame, stations: pd.DataFrame) -> pd.DataFrame:
    """Map each beach to its nearest coord-station in `daily`, exploding rows per
    beach_id (the solar-wind/ocean grids are coarse, many beaches share a cell)."""
    if daily.empty:
        return daily
    grid = daily[["station_id", "latitude", "longitude"]].drop_duplicates("station_id").dropna()
    out = []
    for _, b in stations.iterrows():
        if pd.isna(b.get("latitude")) or pd.isna(b.get("longitude")):
            continue
        nearest, best = None, float("inf")
        for _, s in grid.iterrows():
            d = haversine_km(float(b["latitude"]), float(b["longitude"]), float(s["latitude"]), float(s["longitude"]))
            if d < best:
                nearest, best = str(s["station_id"]), d
        if nearest is None:
            continue
        sub = daily.loc[daily["station_id"] == nearest].copy()
        sub["beach_id"] = str(b["beach_id"])
        out.append(sub)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state", required=True, help="WQP FIPS, e.g. US:48")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    stv = settings.epa_marine_enterococcus_stv
    start_d, end_d = date.fromisoformat(args.start), date.fromisoformat(args.end)
    cache = settings.precip_cache_dir
    wqp_start = start_d.strftime("%m-%d-%Y")
    wqp_end = end_d.strftime("%m-%d-%Y")

    # 1) base observations + stations + beach_day
    obs = fetch_national_wqp([args.state], wqp_start, wqp_end, stv)
    if obs.empty:
        print("[cohort] no observations; abort")
        return 1
    stations = build_wqp_stations(obs)
    bd_obs = to_beach_day_observations(obs)
    adv = pd.DataFrame(columns=["beach_id", "advisory_type", "started_at", "ended_at", "status", "cause", "county", "advisory_website"])
    bd = build_beach_day_frame(bd_obs, stations, adv)
    bd["sample_date"] = pd.to_datetime(bd["sample_date"])
    print(f"[cohort] base beach_day {len(bd)} rows / {bd['beach_id'].nunique()} beaches")

    # 2) hydrology (USGS + Open-Meteo precip)
    links = build_hydrologic_beach_links(stations)
    gage_cov = links["nearest_stream_gage_id"].notna().mean() if not links.empty else 0.0
    print(f"[cohort] hydrology links: {len(links)} | gage coverage {gage_cov*100:.0f}%")
    gage_ids = links["nearest_stream_gage_id"].dropna().unique().tolist() if not links.empty else []
    sf = aggregate_streamflow_windows(asyncio.run(UsgsNwisConnector().fetch_streamflow(gage_ids, start_d, end_d))) if gage_ids else pd.DataFrame()
    pr = pd.DataFrame()
    if not links.empty and {"pour_point_latitude", "pour_point_longitude"}.issubset(links.columns):
        locs = list(zip(*[links[c].dropna() for c in ("pour_point_latitude", "pour_point_longitude")], strict=False))
        raw_pr = asyncio.run(OpenMeteoHistoricalPrecipConnector().fetch_historical_precip(locs, start_d, end_d, cache_dir=cache / "openmeteo"))
        pr = aggregate_precip_windows(raw_pr)
    beach_hydro = build_beach_hydrology_daily(links, sf, pr)
    if not beach_hydro.empty:
        beach_hydro["sample_date"] = pd.to_datetime(beach_hydro["sample_date"])
        bd = bd.merge(beach_hydro, on=["beach_id", "sample_date"], how="left")
        print(f"[cohort] hydrology joined {len(beach_hydro)} rows")

    # 3) marine-micro (solar/UV/wind)
    shore_az = compute_beach_shore_azimuth(stations)
    coastal = compute_beach_coastal_features(stations)
    locs = list({(round(float(r["latitude"]), 1), round(float(r["longitude"]), 1)) for _, r in stations.iterrows() if pd.notna(r.get("latitude"))})
    raw_sw = asyncio.run(OpenMeteoHistoricalSolarWindConnector().fetch_historical_solar_wind(locs, start_d, end_d, cache_dir=cache / "openmeteo_solar_wind"))
    sw_daily = aggregate_solar_wind_windows(raw_sw)
    if not sw_daily.empty:
        sw_daily["sample_date"] = pd.to_datetime(sw_daily["sample_date"])
        beach_sw = _explode_daily_to_beaches(sw_daily, stations)
        if not beach_sw.empty:
            mm = build_marine_microbiology_daily(beach_sw, shore_az)
            mm["sample_date"] = pd.to_datetime(mm["sample_date"])
            bd = bd.merge(mm, on=["beach_id", "sample_date"], how="left").merge(coastal, on="beach_id", how="left")
            print(f"[cohort] marine-micro joined {len(mm)} rows")

    # 4) historical ocean (wave/period/SST) -> CDIP replacement
    raw_oc = asyncio.run(OpenMeteoMarineHistoricalConnector().fetch_marine_history(locs, start_d, end_d, cache_dir=cache / "openmeteo_marine_hist"))
    oc_daily = aggregate_marine_history_daily(raw_oc)
    if not oc_daily.empty:
        oc_daily["sample_date"] = pd.to_datetime(oc_daily["sample_date"])
        beach_oc = _explode_daily_to_beaches(oc_daily, stations)
        if not beach_oc.empty:
            beach_oc = beach_oc.drop(columns=["station_id", "latitude", "longitude"], errors="ignore")
            # don't clobber any same-named columns from earlier joins
            dupes = [c for c in beach_oc.columns if c in bd.columns and c not in ("beach_id", "sample_date")]
            bd = bd.drop(columns=dupes, errors="ignore").merge(beach_oc, on=["beach_id", "sample_date"], how="left")
            print(f"[cohort] ocean joined {len(beach_oc)} rows")

    bd.to_parquet(out / "beach_day.parquet", index=False)
    stations.to_parquet(out / "beaches.parquet", index=False)
    print(f"[cohort] WROTE {out}/beach_day.parquet : {len(bd)} rows x {len(bd.columns)} cols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
