"""Intra-day hourly weather + marine series for a single beach.

Used by the /beaches/{id}/hourly endpoint so the web/mobile detail page
can show a Surfline-style intra-day chart. Two Open-Meteo endpoints:

  * forecast — wind, UV, temperature, shortwave at 10m / surface
  * marine — wave_height, wave_period, wave_direction

Both are free, no auth required, hourly resolution. The 5 AM PT cutoff
applied to the model isn't relevant here — these are forward-looking
forecasts intended to inform "should I go in the water today?" so the
window we expose is yesterday-noon through 48h ahead. Process-level
TTL cache holds results for 3 hours, matching Open-Meteo's marine model
which rebuilds 4× daily (00/06/12/18 UTC). At 3 h TTL each beach hits
upstream at most 8×/day; 330 beaches × 8 = 2,640 calls/day, ~26% of the
10K free-tier limit. This is the cheapest lever for concurrent-user
capacity: see docs/superpowers/research/2026-05-19-concurrent-capacity-debate.md.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

_OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
_OPEN_METEO_MARINE = "https://marine-api.open-meteo.com/v1/marine"
_CACHE_TTL_SECONDS = 60 * 60 * 3  # 3 hours


@dataclass
class _CacheEntry:
    expires_at: float
    payload: dict


# Module-level cache keyed by (lat_rounded, lon_rounded). 0.1° = ~11 km grid;
# matches what we cache for the daily aggregator so we don't double-call.
_CACHE: dict[tuple[float, float], _CacheEntry] = {}


async def _fetch_open_meteo(
    client: httpx.AsyncClient, lat: float, lon: float,
) -> dict | None:
    """Combined forecast + marine call. Returns hourly arrays."""
    forecast_params = {
        "latitude": round(lat, 2),
        "longitude": round(lon, 2),
        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m,uv_index,shortwave_radiation",
        "wind_speed_unit": "ms",
        "temperature_unit": "celsius",
        "timezone": "auto",
        "past_days": 1,
        "forecast_days": 2,
    }
    marine_params = {
        "latitude": round(lat, 2),
        "longitude": round(lon, 2),
        "hourly": "wave_height,wave_period,wave_direction,sea_surface_temperature",
        "timezone": "auto",
        "past_days": 1,
        "forecast_days": 2,
    }
    try:
        forecast_resp, marine_resp = await asyncio.gather(
            client.get(_OPEN_METEO_FORECAST, params=forecast_params, timeout=20.0),
            client.get(_OPEN_METEO_MARINE, params=marine_params, timeout=20.0),
            return_exceptions=True,
        )
    except Exception:
        return None

    forecast: dict = {}
    marine: dict = {}
    if isinstance(forecast_resp, httpx.Response) and forecast_resp.status_code == 200:
        forecast = forecast_resp.json().get("hourly", {}) or {}
    if isinstance(marine_resp, httpx.Response) and marine_resp.status_code == 200:
        marine = marine_resp.json().get("hourly", {}) or {}

    if not forecast.get("time"):
        return None

    # Both endpoints return parallel time arrays starting at the same hour
    # for matching past_days/forecast_days settings — Open-Meteo guarantees this.
    return {
        "time": forecast.get("time", []),
        "air_temperature_c": forecast.get("temperature_2m", []),
        "wind_speed_mps": forecast.get("wind_speed_10m", []),
        "wind_direction_deg": forecast.get("wind_direction_10m", []),
        "uv_index": forecast.get("uv_index", []),
        "shortwave_w_m2": forecast.get("shortwave_radiation", []),
        "wave_height_m": marine.get("wave_height", []),
        "wave_period_s": marine.get("wave_period", []),
        "wave_direction_deg": marine.get("wave_direction", []),
        "water_temperature_c": marine.get("sea_surface_temperature", []),
    }


async def fetch_hourly(lat: float, lon: float) -> dict | None:
    key = (round(lat, 1), round(lon, 1))
    now = time.time()
    cached = _CACHE.get(key)
    if cached and cached.expires_at > now:
        return cached.payload

    async with httpx.AsyncClient(headers={"User-Agent": "Shorelife/1.0"}) as client:
        payload = await _fetch_open_meteo(client, lat, lon)

    if payload is None:
        return None
    _CACHE[key] = _CacheEntry(expires_at=now + _CACHE_TTL_SECONDS, payload=payload)
    return payload
