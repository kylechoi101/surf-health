"""
Turn hourly Open-Meteo Marine data into surf-facing readings:

  build_surf_now(raw, as_of)        — one current-conditions row per spot (the hour
                                      nearest `as_of`): total wave, primary + secondary
                                      swell (height/period/direction + cardinal), wind wave.
  build_surf_daily_forecast(raw)    — per-spot, per-day wave-height range + dominant swell.

Surf height is reported as offshore significant wave height in feet, bracketed into a
range to reflect set-wave variability. Translating offshore swell to the breaking-wave
*face* height at a specific break needs per-spot swell-window modeling — that's the
deferred fast-follow, so we honestly label these as wave heights, not face heights.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_M_TO_FT = 3.28084
# Sets run larger than the significant height; give an honest low/high bracket.
_WAVE_RANGE_LOW = 0.9
_WAVE_RANGE_HIGH = 1.3

_CARDINALS_16 = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]

_NOW_COLS = [
    "station_id", "latitude", "longitude", "as_of_utc", "observed_time_utc",
    "wave_height_m", "wave_period_s", "wave_direction_deg",
    "wave_height_ft_min", "wave_height_ft_max",
    "primary_swell_height_m", "primary_swell_period_s",
    "primary_swell_direction_deg", "primary_swell_direction_cardinal",
    "secondary_swell_height_m", "secondary_swell_period_s",
    "secondary_swell_direction_deg", "secondary_swell_direction_cardinal",
    "wind_wave_height_m",
]

_DAILY_COLS = [
    "station_id", "latitude", "longitude", "forecast_date",
    "wave_height_m_mean", "wave_height_m_max",
    "wave_height_ft_min", "wave_height_ft_max",
    "primary_swell_period_s", "primary_swell_direction_deg",
    "primary_swell_direction_cardinal",
]


def degrees_to_cardinal(deg: float | None) -> str | None:
    """Map a compass bearing (deg, 'from' convention) to a 16-point cardinal label."""
    if deg is None or (isinstance(deg, float) and np.isnan(deg)):
        return None
    idx = int(round(float(deg) / 22.5)) % 16
    return _CARDINALS_16[idx]


def _ft_range(height_m: float) -> tuple[float, float]:
    if height_m is None or np.isnan(height_m):
        return (np.nan, np.nan)
    ft = height_m * _M_TO_FT
    return (round(ft * _WAVE_RANGE_LOW, 1), round(ft * _WAVE_RANGE_HIGH, 1))


def _prep(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["time_utc", "station_id"])
    return df.sort_values(["station_id", "time_utc"])


def build_surf_now(raw: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """One current-conditions row per station — the hour nearest `as_of`."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=_NOW_COLS)

    df = _prep(raw)
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")

    rows = []
    for station_id, sdf in df.groupby("station_id"):
        nearest = sdf.iloc[(sdf["time_utc"] - as_of).abs().to_numpy().argmin()]
        ft_min, ft_max = _ft_range(float(nearest["wave_height"]))
        rows.append({
            "station_id": station_id,
            "latitude": float(nearest["latitude"]),
            "longitude": float(nearest["longitude"]),
            "as_of_utc": as_of,
            "observed_time_utc": nearest["time_utc"],
            "wave_height_m": float(nearest["wave_height"]),
            "wave_period_s": float(nearest["wave_period"]),
            "wave_direction_deg": float(nearest["wave_direction"]),
            "wave_height_ft_min": ft_min,
            "wave_height_ft_max": ft_max,
            "primary_swell_height_m": float(nearest["swell_wave_height"]),
            "primary_swell_period_s": float(nearest["swell_wave_period"]),
            "primary_swell_direction_deg": float(nearest["swell_wave_direction"]),
            "primary_swell_direction_cardinal": degrees_to_cardinal(nearest["swell_wave_direction"]),
            "secondary_swell_height_m": float(nearest["secondary_swell_wave_height"]),
            "secondary_swell_period_s": float(nearest["secondary_swell_wave_period"]),
            "secondary_swell_direction_deg": float(nearest["secondary_swell_wave_direction"]),
            "secondary_swell_direction_cardinal": degrees_to_cardinal(nearest["secondary_swell_wave_direction"]),
            "wind_wave_height_m": float(nearest["wind_wave_height"]),
        })
    return pd.DataFrame(rows, columns=_NOW_COLS)


def build_surf_daily_forecast(raw: pd.DataFrame) -> pd.DataFrame:
    """Per-station, per-day wave-height range + dominant (longest-period) swell."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=_DAILY_COLS)

    df = _prep(raw)
    df["forecast_date"] = df["time_utc"].dt.tz_convert("America/Los_Angeles").dt.date

    rows = []
    for (station_id, fdate), g in df.groupby(["station_id", "forecast_date"]):
        wh_mean = float(g["wave_height"].mean())
        wh_max = float(g["wave_height"].max())
        ft_min, ft_max = _ft_range(wh_max)
        # Dominant swell for the day = the hour with the longest primary swell period.
        dom = g.loc[g["swell_wave_period"].idxmax()]
        rows.append({
            "station_id": station_id,
            "latitude": float(g["latitude"].iloc[0]),
            "longitude": float(g["longitude"].iloc[0]),
            "forecast_date": fdate,
            "wave_height_m_mean": round(wh_mean, 2),
            "wave_height_m_max": round(wh_max, 2),
            "wave_height_ft_min": ft_min,
            "wave_height_ft_max": ft_max,
            "primary_swell_period_s": float(dom["swell_wave_period"]),
            "primary_swell_direction_deg": float(dom["swell_wave_direction"]),
            "primary_swell_direction_cardinal": degrees_to_cardinal(dom["swell_wave_direction"]),
        })
    return pd.DataFrame(rows, columns=_DAILY_COLS).sort_values(
        ["station_id", "forecast_date"]
    ).reset_index(drop=True)
