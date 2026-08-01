"""Forecast-time weather pull — 100% coverage wind/UV/shortwave for every beach.

The existing solar_wind ingest only attaches weather to beach_day rows that have
an Enterococcus sample on that day, leaving the latest_env lookup at ~41% wind/UV
coverage. This module fixes that by hitting Open-Meteo's forecast endpoint at
each beach's lat/lon at forecast time, independent of sample cadence.

Key advantages over the archive endpoint:
  * Returns uv_index (archive does not — UV is forecast-only in Open-Meteo)
  * Returns past_days observations, so we keep the 5 AM PT forecast-safe cutoff
  * Same provider, same units, same auth (none) — drop-in supplement

NDBC buoy data is layered in for coastal beaches when a buoy is within 25 km;
buoy observations beat reanalysis when both are available.

Output: a DataFrame with one row per beach, columns ready to slot into
latest_env.parquet.
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd

from app.core.geo import haversine_km as _haversine_km


from app.core.timewindows import forecast_cutoff_utc as _forecast_cutoff_utc
from app.data.pipeline.solar_wind import uv_index_24h_max


def _uv_or_none(uv, shortwave) -> float | None:
    value, _is_proxy = uv_index_24h_max(uv, shortwave)
    return None if value != value else float(value)  # NaN -> None


_PACIFIC = ZoneInfo("America/Los_Angeles")
_OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
_NDBC_LATEST = "https://www.ndbc.noaa.gov/data/latest_obs/{station}.txt"

# Subset of NDBC stations along the California coast that report wind reliably.
# Curated from https://www.ndbc.noaa.gov/data/stations/stations.shtml; CA-only.
_CA_BUOYS: list[tuple[str, float, float]] = [
    ("46011", 34.956, -120.992),  # Santa Maria
    ("46012", 37.363, -122.881),  # Half Moon Bay
    ("46013", 38.242, -123.301),  # Bodega Bay
    ("46014", 39.220, -123.974),  # Pt Arena
    ("46022", 40.748, -124.527),  # Eel River
    ("46025", 33.749, -119.053),  # Catalina Ridge
    ("46026", 37.755, -122.839),  # San Francisco
    ("46027", 41.850, -124.382),  # St. Georges
    ("46028", 35.741, -121.884),  # Cape San Martin
    ("46042", 36.789, -122.398),  # Monterey
    ("46047", 32.388, -119.495),  # Tanner Banks
    ("46050", 44.641, -124.524),  # Stonewall Bank (OR border)
    ("46053", 34.241, -119.840),  # E Santa Barbara
    ("46054", 34.265, -120.443),  # W Santa Barbara
    ("46059", 38.082, -129.926),  # West California
    ("46069", 33.679, -120.213),  # S Santa Rosa I
    ("46086", 32.499, -118.052),  # San Clemente Basin
    ("46219", 33.221, -119.882),  # San Nicolas
    ("46221", 33.860, -118.633),  # Santa Monica Bay
    ("46222", 33.617, -118.318),  # San Pedro
    ("46223", 32.943, -117.391),  # Pt Loma
    ("46224", 33.179, -117.470),  # Oceanside Offshore
    ("46225", 32.755, -117.501),  # Torrey Pines Outer
    ("46232", 32.530, -117.428),  # Pt Loma South
    ("46237", 37.788, -122.633),  # SF Bar
    ("46239", 36.341, -122.102),  # Pt Sur
    ("46251", 33.769, -119.566),  # Santa Cruz Basin
    ("46253", 33.578, -118.181),  # San Pedro South
    ("46256", 33.737, -118.171),  # Long Beach Outer
    ("46258", 33.485, -117.751),  # San Mateo
]

_BUOY_MAX_DISTANCE_KM = 25.0


def _nearest_buoy(lat: float, lon: float) -> tuple[str, float] | None:
    """Return (station_id, distance_km) of the closest NDBC buoy within range."""
    best = None
    best_d = _BUOY_MAX_DISTANCE_KM
    for sid, blat, blon in _CA_BUOYS:
        d = _haversine_km(lat, lon, blat, blon)
        if d < best_d:
            best_d = d
            best = sid
    return (best, best_d) if best else None


@dataclass
class WeatherSnapshot:
    beach_id: str
    wind_speed_mps: float | None
    wind_direction_deg: float | None
    uv_index: float | None
    shortwave_24h_sum: float | None
    source: str  # "openmeteo" | "ndbc+openmeteo" | "unavailable"


async def _fetch_openmeteo(
    client: httpx.AsyncClient, lat: float, lon: float, forecast_date: date,
) -> dict | None:
    """One Open-Meteo forecast call; returns the 24h window ending at the
    forecast-safe 5 AM PT cutoff. past_days=2 covers cases where we're called
    before midnight UTC.
    """
    cutoff = _forecast_cutoff_utc(forecast_date)
    window_start = cutoff - pd.Timedelta(hours=24)

    try:
        r = await client.get(_OPEN_METEO_FORECAST, params={
            "latitude": round(lat, 2),
            "longitude": round(lon, 2),
            "hourly": "wind_speed_10m,wind_direction_10m,uv_index,shortwave_radiation",
            "wind_speed_unit": "ms",
            "timezone": "UTC",
            "past_days": 2,
            "forecast_days": 1,
        }, timeout=20.0)
        r.raise_for_status()
        payload = r.json().get("hourly", {})
    except Exception:
        return None

    times = pd.to_datetime(payload.get("time", []), utc=True)
    if len(times) == 0:
        return None

    mask = (times >= window_start) & (times < cutoff)
    if not mask.any():
        return None

    def _arr(key: str) -> np.ndarray:
        vals = payload.get(key, [])
        return np.array([np.nan if v is None else float(v) for v in vals])

    ws = _arr("wind_speed_10m")[mask]
    wd = _arr("wind_direction_10m")[mask]
    uv = _arr("uv_index")[mask]
    sw = _arr("shortwave_radiation")[mask]

    # Vector-average wind direction
    valid = ~(np.isnan(ws) | np.isnan(wd))
    if valid.any():
        dir_rad = np.deg2rad(wd[valid])
        u = -ws[valid] * np.sin(dir_rad)
        v = -ws[valid] * np.cos(dir_rad)
        wd_mean = float((math.degrees(math.atan2(-u.mean(), -v.mean())) + 360) % 360)
    else:
        wd_mean = None

    return {
        "wind_speed_mps": float(np.nanmax(ws)) if not np.isnan(ws).all() else None,
        "wind_direction_deg": wd_mean,
        # Same UV policy as the archive-side aggregator. The forecast endpoint
        # normally returns real modelled UV, so this takes the real branch and
        # the proxy is only reached if that ever stops being true — previously
        # this returned None there while solar_wind fell back, so an endpoint
        # change would have silently blanked the served value while the trained
        # feature kept a number.
        "uv_index": _uv_or_none(uv, sw),
        "shortwave_24h_sum": float(np.nansum(sw)) * 3600 / 1e6 if not np.isnan(sw).all() else None,
    }


async def _fetch_ndbc(client: httpx.AsyncClient, station: str) -> dict | None:
    """Pull the latest observation from an NDBC buoy. Returns wind only;
    UV/shortwave are not in standard buoy meteorological reports.

    NDBC's latest_obs.txt has a "key: value" multi-line format. Robust to any
    parse failure — falls through to Open-Meteo on error.
    """
    try:
        r = await client.get(_NDBC_LATEST.format(station=station), timeout=15.0)
        if r.status_code != 200:
            return None
        text = r.text
    except Exception:
        return None

    # latest_obs.txt example: "Wind: NW (320°), 5.8 kt"
    import re
    try:
        m = re.search(r"Wind:.*?\((\d+)\D*\)[,\s]+([\d.]+)\s*kt", text)
        if not m:
            return None
        wdir = float(m.group(1))
        wspd_kt = float(m.group(2))
        if math.isnan(wdir) or math.isnan(wspd_kt):
            return None
        if wspd_kt >= 99 or wdir >= 999 or wspd_kt < 0:
            return None
        return {
            "wind_speed_mps": wspd_kt * 0.5144,  # knots → m/s
            "wind_direction_deg": wdir,
        }
    except Exception:
        return None


async def collect_forecast_weather(
    beaches: pd.DataFrame, forecast_date: date,
) -> pd.DataFrame:
    """One row per beach. ``beaches`` must have columns beach_id, latitude, longitude.

    Open-Meteo's free tier rate-limits, so we (a) dedupe coordinates at 0.1°
    precision (~11 km grid) and (b) cap concurrency at 4 with retry. 723
    California beaches collapse to ~150 unique 0.1° grid points.
    """
    if beaches.empty:
        return pd.DataFrame(columns=[
            "beach_id", "wind_speed_mps", "wind_direction_deg",
            "uv_index", "shortwave_24h_sum", "weather_source",
        ])

    work = beaches.copy()
    work["_lat_r"] = work["latitude"].round(1)
    work["_lon_r"] = work["longitude"].round(1)
    unique_coords = work[["_lat_r", "_lon_r"]].drop_duplicates().reset_index(drop=True)

    async with httpx.AsyncClient(headers={"User-Agent": "Shorelife/1.0"}) as client:
        sem = asyncio.Semaphore(4)

        async def _per_coord(lat: float, lon: float) -> dict | None:
            async with sem:
                # Retry once on transient error
                for _attempt in range(2):
                    om = await _fetch_openmeteo(client, lat, lon, forecast_date)
                    if om is not None:
                        return om
                    await asyncio.sleep(0.5)
                return None

        om_results = await asyncio.gather(
            *[_per_coord(float(r["_lat_r"]), float(r["_lon_r"])) for _, r in unique_coords.iterrows()]
        )
        coord_lookup = {
            (float(r["_lat_r"]), float(r["_lon_r"])): res
            for (_, r), res in zip(unique_coords.iterrows(), om_results)
        }

        # NDBC pulls: one per unique nearest-buoy, not per beach
        buoys_needed: set[str] = set()
        for _, row in work.iterrows():
            buoy = _nearest_buoy(float(row["latitude"]), float(row["longitude"]))
            if buoy is not None:
                buoys_needed.add(buoy[0])

        ndbc_results = await asyncio.gather(
            *[_fetch_ndbc(client, sid) for sid in buoys_needed]
        )
        ndbc_lookup = {sid: res for sid, res in zip(buoys_needed, ndbc_results) if res is not None}

    snapshots: list[dict] = []
    for _, row in work.iterrows():
        bid = row["beach_id"]
        lat_r = float(row["_lat_r"])
        lon_r = float(row["_lon_r"])
        om = coord_lookup.get((lat_r, lon_r))
        if om is None:
            snapshots.append({"beach_id": bid, "weather_source": "unavailable",
                              "wind_speed_mps": None, "wind_direction_deg": None,
                              "uv_index": None, "shortwave_24h_sum": None})
            continue

        out = dict(om)
        buoy = _nearest_buoy(float(row["latitude"]), float(row["longitude"]))
        if buoy is not None and buoy[0] in ndbc_lookup:
            out["wind_speed_mps"] = ndbc_lookup[buoy[0]]["wind_speed_mps"]
            out["wind_direction_deg"] = ndbc_lookup[buoy[0]]["wind_direction_deg"]
            source = f"ndbc:{buoy[0]}+openmeteo"
        else:
            source = "openmeteo"

        snapshots.append({"beach_id": bid, "weather_source": source, **out})

    return pd.DataFrame(snapshots)


def patch_latest_env(latest_env: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """Overwrite wind/UV/shortwave columns in latest_env with the forecast-time
    weather pull. Leaves wave/temp/salinity alone — those come from sampled
    history and shouldn't be replaced.
    """
    out = latest_env.merge(weather, on="beach_id", how="left", suffixes=("_old", ""))
    for col in ("wind_speed_mps", "wind_direction_deg", "uv_index"):
        old_col = f"{col}_old"
        if old_col in out.columns:
            # Prefer new (forecast-time) value; fall back to old (sample-time)
            out[col] = out[col].combine_first(out[old_col])
            out = out.drop(columns=[old_col])
    return out
