"""
Aggregate hourly Open-Meteo solar / cloud / wind into forecast-safe daily windows.
Mirrors precipitation.py — uses 5 AM PT as the daily forecast cutoff to avoid
leaking same-morning sample data into features.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.core.timewindows import forecast_cutoff_utc as _forecast_cutoff_utc

# Peak clear-noon shortwave in CA is ~900 W/m^2, which corresponds to a UV index
# of ~11; 900/80 = 11.25. Cloudy ~300 W/m^2 -> ~3.75.
UV_FROM_SHORTWAVE_DIVISOR = 80.0
UV_INDEX_CEILING = 15.0


def uv_index_24h_max(uv_values, shortwave_values) -> tuple[float, bool]:
    """Peak UV index over a window, and whether it is the shortwave proxy.

    Open-Meteo's ARCHIVE API returns null for uv_index (it is a forecast-only
    variable) — measured at 0 non-null across 172,512 cached hourly rows — so
    every historical value the model trains on is the proxy below. The FORECAST
    endpoint does return real modelled UV, which is why the served ``uv_index``
    in latest_env.parquet runs ~43% above the trained ``uv_index_24h_max``.

    Both producers now share this one policy so the divisor, the ceiling and the
    prefer-real-then-fall-back order cannot drift apart, and the boolean makes
    the provenance explicit at the call site instead of implicit in a comment.
    """
    if uv_values is not None:
        uv = np.asarray(uv_values, dtype=float)
        if uv.size and not np.isnan(uv).all():
            return float(np.nanmax(uv)), False
    if shortwave_values is not None:
        sw = np.asarray(shortwave_values, dtype=float)
        if sw.size and not np.isnan(sw).all():
            peak = float(np.nanmax(sw))
            proxy = max(0.0, min(UV_INDEX_CEILING, peak / UV_FROM_SHORTWAVE_DIVISOR))
            return proxy, True
    return float("nan"), False


_PACIFIC = ZoneInfo("America/Los_Angeles")


def aggregate_solar_wind_windows(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate hourly solar/wind into daily summaries keyed by (station_id, sample_date).
    Each row represents what was observable as of 5 AM PT on `sample_date` — every
    aggregation uses ONLY hours strictly before the cutoff.

    Output columns:
      station_id, latitude, longitude, sample_date,
      cloud_cover_24h_mean      — daytime cloud cover, % (avg of preceding 24 h)
      shortwave_24h_sum         — total surface SW radiation in MJ/m² (preceding 24 h)
      uv_index_24h_max          — peak modeled UV index in preceding 24 h
      wind_u_24h_mean           — eastward wind component, m/s (preceding 24 h)
      wind_v_24h_mean           — northward wind component, m/s (preceding 24 h)
      wind_speed_24h_max        — peak wind speed, m/s (preceding 24 h)
      days_since_sunny          — days since cloud_cover_24h_mean was ≤ 30 %
                                  (capped at 30; NaN until first sunny day seen)
    """
    output_cols = [
        "station_id", "latitude", "longitude", "sample_date",
        "cloud_cover_24h_mean", "shortwave_24h_sum", "uv_index_24h_max",
        "wind_u_24h_mean", "wind_v_24h_mean", "wind_speed_24h_max",
        "wind_direction_24h_mean",
        "days_since_sunny",
    ]
    if raw.empty:
        return pd.DataFrame(columns=output_cols)

    df = raw.copy()
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True, errors="coerce")
    for col in ("cloud_cover", "shortwave_radiation", "uv_index", "wind_speed_10m", "wind_direction_10m"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["time_utc", "station_id"])
    df = df.drop_duplicates(subset=["station_id", "time_utc"], keep="last")
    if df.empty:
        return pd.DataFrame(columns=output_cols)

    # Decompose wind into u (east) / v (north) components from speed + direction.
    # Met convention: wind_direction is the direction wind is FROM. The vector pointing
    # in the direction the wind is GOING is rotated 180°. For onshore-component computation
    # downstream we want the "flow" vector (where the air is going), which is the standard
    # u/v decomposition: u = -speed*sin(dir_rad), v = -speed*cos(dir_rad).
    if "wind_speed_10m" in df.columns and "wind_direction_10m" in df.columns:
        dir_rad = np.deg2rad(df["wind_direction_10m"])
        df["wind_u"] = -df["wind_speed_10m"] * np.sin(dir_rad)
        df["wind_v"] = -df["wind_speed_10m"] * np.cos(dir_rad)
    else:
        df["wind_u"] = np.nan
        df["wind_v"] = np.nan

    rows = []
    for station_id, sdf in df.groupby("station_id"):
        sdf = sdf.set_index("time_utc").sort_index()
        lat = float(sdf["latitude"].iloc[0])
        lon = float(sdf["longitude"].iloc[0])
        min_date = sdf.index.min().date()
        max_date = sdf.index.max().date()

        for d in pd.date_range(min_date, max_date, freq="D"):
            cutoff = _forecast_cutoff_utc(d.date())
            window_start = cutoff - pd.Timedelta(hours=24)
            window = sdf.loc[(sdf.index >= window_start) & (sdf.index < cutoff)]
            if window.empty:
                continue

            cc_mean = float(window["cloud_cover"].mean()) if "cloud_cover" in window else np.nan
            sw_sum_wm2_h = float(window["shortwave_radiation"].sum()) if "shortwave_radiation" in window else np.nan
            sw_mj = sw_sum_wm2_h * 3600 / 1e6 if not np.isnan(sw_sum_wm2_h) else np.nan
            uv_max, _uv_is_proxy = uv_index_24h_max(
                window["uv_index"] if "uv_index" in window else None,
                window["shortwave_radiation"] if "shortwave_radiation" in window else None,
            )
            u_mean = float(window["wind_u"].mean()) if "wind_u" in window else np.nan
            v_mean = float(window["wind_v"].mean()) if "wind_v" in window else np.nan
            ws_max = float(window["wind_speed_10m"].max()) if "wind_speed_10m" in window else np.nan
            # Vector-average wind direction from u/v means. Convert back to
            # "wind from" meteorological convention (degrees clockwise from north).
            wd_mean: float = np.nan
            if not np.isnan(u_mean) and not np.isnan(v_mean) and (u_mean != 0 or v_mean != 0):
                wd_mean = float((np.rad2deg(np.arctan2(-u_mean, -v_mean)) + 360) % 360)

            rows.append({
                "station_id": station_id,
                "latitude": lat,
                "longitude": lon,
                "sample_date": d.date(),
                "cloud_cover_24h_mean": cc_mean,
                "shortwave_24h_sum": sw_mj,
                "uv_index_24h_max": uv_max,
                "wind_u_24h_mean": u_mean,
                "wind_v_24h_mean": v_mean,
                "wind_speed_24h_max": ws_max,
                "wind_direction_24h_mean": wd_mean,
            })

    if not rows:
        return pd.DataFrame(columns=output_cols)
    out = pd.DataFrame(rows).sort_values(["station_id", "sample_date"]).reset_index(drop=True)

    # days_since_sunny — per station, days since cloud_cover_24h_mean ≤ 30 %
    SUN_THRESHOLD = 30.0
    parts: list[pd.Series] = []
    for _, grp in out.groupby("station_id", sort=False):
        sunny = (grp["cloud_cover_24h_mean"] <= SUN_THRESHOLD).reset_index(drop=True)
        # Last sunny day's date for each row's date (forecast-safe via shift + ffill)
        days = grp["sample_date"].reset_index(drop=True)
        sunny_date = pd.Series(np.where(sunny, days, pd.NaT), index=grp.index)
        last_sunny = sunny_date.shift(1).ffill()
        days_idx = pd.to_datetime(grp["sample_date"])
        last_sunny_dt = pd.to_datetime(last_sunny)
        delta = (days_idx.values - last_sunny_dt.values).astype("timedelta64[D]").astype("float64")
        parts.append(pd.Series(np.clip(delta, 0, 30), index=grp.index))

    out["days_since_sunny"] = pd.concat(parts).sort_index() if parts else np.nan
    return out
