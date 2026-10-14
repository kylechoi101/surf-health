"""Rebuild the history of solar_wind_daily.parquet back to 2020 for every grid cell.

On 2026-10-13, 116 of 123 grid cells in the committed file started on 2026-04-20 or
later, because the pipeline's incremental fetch never fetched history for cells that
joined the roster after the file was first built. The pipeline now backfills such cells
itself (``solar_wind_backfill_plan``); this script does the same once, offline, so the
committed file carries the history and the daily run does not have to fetch ~800 archive
ranges. It uses the same plan, connectors and aggregation as ``--with-solar-wind`` and
reuses the cached archive files; only missing ranges go to the network.

    cd backend && .venv/bin/python scripts/backfill_solar_wind.py
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.data.connectors.hydrology_sources import (  # noqa: E402
    OpenMeteoHistoricalSolarWindConnector,
    OpenMeteoHistoricalUvConnector,
)
from app.data.pipeline.solar_wind import (  # noqa: E402
    aggregate_solar_wind_windows,
    merge_uv_hourly,
    solar_wind_backfill_plan,
)

FULL_START = date(2020, 1, 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--curated", type=Path, default=get_settings().curated_dir)
    ap.add_argument("--cache", type=Path, default=get_settings().precip_cache_dir)
    ap.add_argument("--fill-gaps", action="store_true",
                    help="refetch every cell with a missing day before the incremental start "
                         "(e.g. after Open-Meteo answered 429), one request at a time")
    args = ap.parse_args()

    path = args.curated / "solar_wind_daily.parquet"
    existing = pd.read_parquet(path)
    locs = sorted({(round(float(a), 1), round(float(b), 1)) for a, b in zip(existing["latitude"], existing["longitude"])})
    fetch_start = max(FULL_START, (pd.to_datetime(existing["sample_date"]).max() - pd.Timedelta(days=7)).date())
    cells, ranges = solar_wind_backfill_plan(existing, locs, FULL_START, fetch_start)
    concurrency = OpenMeteoHistoricalSolarWindConnector.concurrency
    if args.fill_gaps:
        days = pd.to_datetime(existing["sample_date"])
        window = (days >= pd.Timestamp(FULL_START)) & (days < pd.Timestamp(fetch_start))
        have = days[window].groupby(existing.loc[window, "station_id"].astype(str)).nunique()
        expected = (fetch_start - FULL_START).days
        cells = [loc for loc in locs if have.get(f"{loc[0]}_{loc[1]}", 0) < expected]
        ranges = solar_wind_backfill_plan(None, cells, FULL_START, fetch_start)[1]
        concurrency = 1
    print(f"[backfill] {len(locs)} cells on file; {len(cells)} need history; {len(ranges)} ranges up to {fetch_start}")
    if not cells:
        return

    solar, uv_conn = OpenMeteoHistoricalSolarWindConnector(), OpenMeteoHistoricalUvConnector()
    solar.concurrency = uv_conn.concurrency = concurrency
    sw_frames, uv_frames = [], []
    for lo, hi in ranges:
        sw = asyncio.run(solar.fetch_historical_solar_wind(
            cells, lo, hi, cache_dir=args.cache / "openmeteo_solar_wind"))
        uv = asyncio.run(uv_conn.fetch_historical_uv(
            cells, lo, hi, cache_dir=args.cache / "openmeteo_uv"))
        print(f"[backfill] {lo} → {hi}: solar/wind hours {len(sw)}, UV hours {len(uv)}", flush=True)
        sw_frames.append(sw)
        if not uv.empty:
            uv_frames.append(uv)

    raw_uv = pd.concat(uv_frames, ignore_index=True) if uv_frames else pd.DataFrame()
    new = aggregate_solar_wind_windows(merge_uv_hourly(pd.concat(sw_frames, ignore_index=True), raw_uv))
    new = new[pd.to_datetime(new["sample_date"]) < pd.Timestamp(fetch_start)]

    # Same merge as the pipeline: newer rows win, so a cell's first days (computed
    # without the days before them) are replaced by rows built on full history.
    out = (
        pd.concat([existing, new], ignore_index=True)
        .assign(sample_date=lambda f: pd.to_datetime(f["sample_date"]).dt.date)
        .drop_duplicates(subset=["station_id", "sample_date"], keep="last")
        .sort_values(["station_id", "sample_date"])
        .reset_index(drop=True)
    )
    first = pd.to_datetime(out["sample_date"]).groupby(out["station_id"]).min()
    print(f"[backfill] rows {len(existing)} → {len(out)}; cells starting 2020: "
          f"{int((first < pd.Timestamp('2020-02-01')).sum())} of {first.size}")
    out.to_parquet(path, index=False)


if __name__ == "__main__":
    main()
