"""Refresh latest_env.parquet with forecast-time wind/UV from Open-Meteo + NDBC.

Runs after ML training in the daily-forecast CI. Independent of sample cadence
so every beach gets current wind/UV regardless of when it was last sampled.

Usage:
    python scripts/refresh_latest_env_weather.py --forecast-date 2026-05-12
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date
from pathlib import Path

import pandas as pd

from app.data.pipeline.forecast_weather import collect_forecast_weather, patch_latest_env


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--curated", default="../data/curated", help="curated data dir")
    p.add_argument("--forecast-date", required=True, help="YYYY-MM-DD")
    args = p.parse_args()

    curated = Path(args.curated)
    fc_date = date.fromisoformat(args.forecast_date)

    beaches = pd.read_parquet(curated / "beaches.parquet")
    beaches = beaches.loc[beaches["support_status"] == "production"]
    coords = beaches[["beach_id", "latitude", "longitude"]].dropna()

    print(f"Pulling forecast-time weather for {len(coords)} production beaches…")
    weather = asyncio.run(collect_forecast_weather(coords, fc_date))

    n_om = (weather["weather_source"] == "openmeteo").sum()
    n_ndbc = (weather["weather_source"].str.startswith("ndbc:", na=False)).sum()
    n_none = (weather["weather_source"] == "unavailable").sum()
    print(f"  open-meteo only: {n_om}  |  ndbc+open-meteo: {n_ndbc}  |  unavailable: {n_none}")

    latest_env_path = curated / "latest_env.parquet"
    if latest_env_path.exists():
        latest_env = pd.read_parquet(latest_env_path)
    else:
        latest_env = pd.DataFrame({"beach_id": weather["beach_id"]})

    merged = patch_latest_env(latest_env, weather.drop(columns=["weather_source"]))

    # Stats
    for col in ("wind_speed_mps", "uv_index", "wind_direction_deg"):
        if col in merged.columns:
            nn = merged[col].notna().sum()
            print(f"  latest_env.{col}: {nn}/{len(merged)} non-null")

    merged.to_parquet(latest_env_path, index=False)
    print(f"Wrote {latest_env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
