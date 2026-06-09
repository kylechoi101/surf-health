"""Precompute the per-beach hourly forecast+marine series into a parquet so the
``/beaches/{id}/hourly`` API route can serve it from disk instead of calling
Open-Meteo live on every request.

Why: the live per-request path (``app/services/hourly_weather.fetch_hourly``)
gets rate-limited / IP-blocked from the production server (Render datacenter IP),
returning 502 "upstream weather service unavailable" — which wipes out ALL surf
data in the app (surf ratings + the surf detail screen both read /hourly). The
daily CI runner fetches Open-Meteo from a different IP that isn't throttled, so
we bake the payloads here and ship them with the snapshot.

Keyed by the same 0.1° lat/lon grid cell the live cache uses, so the route can
round a beach's coordinates and look it up. One JSON payload per cell keeps the
parquet small and the route reconstruction trivial.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pandas as pd

from app.services.hourly_weather import _fetch_open_meteo


async def _fetch_all(coords: list[tuple[float, float]], concurrency: int = 6) -> dict[tuple[float, float], dict]:
    sem = asyncio.Semaphore(concurrency)
    out: dict[tuple[float, float], dict] = {}
    async with httpx.AsyncClient(headers={"User-Agent": "Shorelife/1.0"}) as client:
        async def one(lat: float, lon: float) -> None:
            async with sem:
                payload = await _fetch_open_meteo(client, lat, lon)
            if payload is not None and payload.get("time"):
                out[(lat, lon)] = payload

        await asyncio.gather(*(one(lat, lon) for lat, lon in coords))
    return out


def build_hourly_forecast(beaches: pd.DataFrame) -> pd.DataFrame:
    """Fetch hourly forecast+marine for every unique 0.1° cell among ``beaches``.

    Returns a frame with columns ``lat_r``, ``lon_r``, ``payload_json`` — one row
    per grid cell. Cells whose upstream fetch fails are simply omitted (the route
    falls back to a live fetch for those).
    """
    if beaches.empty or "latitude" not in beaches.columns:
        return pd.DataFrame(columns=["lat_r", "lon_r", "payload_json"])

    lat = pd.to_numeric(beaches["latitude"], errors="coerce")
    lon = pd.to_numeric(beaches["longitude"], errors="coerce")
    coords = sorted(
        {
            (round(float(a), 1), round(float(o), 1))
            for a, o in zip(lat, lon)
            if pd.notna(a) and pd.notna(o)
        }
    )
    if not coords:
        return pd.DataFrame(columns=["lat_r", "lon_r", "payload_json"])

    payloads = asyncio.run(_fetch_all(coords))
    rows = [
        {"lat_r": lat_r, "lon_r": lon_r, "payload_json": json.dumps(payload)}
        for (lat_r, lon_r), payload in payloads.items()
    ]
    return pd.DataFrame(rows, columns=["lat_r", "lon_r", "payload_json"])
