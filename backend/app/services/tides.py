"""Tide predictions for California beaches from NOAA CO-OPS.

Used by the /beaches/{id}/tides endpoint. NOAA CO-OPS is free, no auth
required, and returns deterministic harmonic predictions — there is no
"forecast" component to invalidate so we can cache aggressively (24 h).

Returns 48 h of predictions at hourly resolution plus a derived
extrema list (high/low tide events) detected as local maxima/minima
in the predictions array.

Station selection is a haversine nearest-neighbor against a small
hardcoded list of ~22 CA stations spanning the entire coast (Crescent
City → San Diego). The list is short enough that a linear scan is
faster than any indexed lookup.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from app.core.geo import haversine_km as _haversine_km


_NOAA_DATAGETTER = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 hours — harmonic predictions are deterministic
_PREDICTION_HOURS = 48
# How many hours BEFORE now to include in the response. The clients render
# a ±8h window centered on now, so without past-hour data the left half of
# the tide chart is empty. Backend pulls 8h of past + 48h of future for a
# total ~56h response per station per request (still cached for 24h).
_PAST_PREDICTION_HOURS = 10


# California NOAA CO-OPS tide stations, ordered roughly N→S along the coast.
# All station IDs verified against https://tidesandcurrents.noaa.gov/stations.html
# (filter: state=CA, type=harmonic).
CA_TIDE_STATIONS: tuple[tuple[str, str, float, float], ...] = (
    ("9419750", "Crescent City", 41.7456, -124.1844),
    ("9418767", "North Spit, Humboldt Bay", 40.7667, -124.2167),
    ("9418723", "North Jetty, Humboldt Bay", 40.7667, -124.2333),
    ("9416841", "Arena Cove", 38.9145, -123.7113),
    ("9415020", "Point Reyes", 37.9961, -122.9744),
    ("9415118", "Bodega Harbor Entrance", 38.3170, -123.0500),
    ("9414750", "Alameda", 37.7717, -122.3000),
    ("9414290", "San Francisco", 37.8063, -122.4659),
    ("9413450", "Monterey", 36.6050, -121.8881),
    ("9413745", "Santa Cruz", 36.9583, -122.0167),
    ("9412110", "Port San Luis", 35.1686, -120.7542),
    ("9411406", "Oceano Beach Pier", 35.1011, -120.6300),
    ("9411340", "Santa Barbara", 34.4036, -119.6925),
    ("9411270", "Rincon Island, Mussel Shoals", 34.3500, -119.4400),
    ("9410840", "Santa Monica", 34.0083, -118.5000),
    ("9410660", "Los Angeles", 33.7200, -118.2728),
    ("9410680", "Long Beach Pier J", 33.7400, -118.1869),
    ("9410665", "Los Angeles Pilot Station", 33.7158, -118.2706),
    ("9410580", "Newport Bay Entrance", 33.6028, -117.8819),
    ("9410230", "La Jolla", 32.8669, -117.2571),
    ("9410170", "San Diego", 32.7142, -117.1736),
    ("9410079", "Mission Bay Entrance", 32.7800, -117.2533),
)


@dataclass
class _CacheEntry:
    expires_at: float
    payload: dict


_CACHE: dict[str, _CacheEntry] = {}


def nearest_station(lat: float, lon: float) -> tuple[str, str, float]:
    """Return (station_id, station_name, distance_km) for the closest CA station."""
    best_id = ""
    best_name = ""
    best_dist = float("inf")
    for sid, name, slat, slon in CA_TIDE_STATIONS:
        d = _haversine_km(lat, lon, slat, slon)
        if d < best_dist:
            best_dist = d
            best_id = sid
            best_name = name
    return best_id, best_name, best_dist


def detect_extrema(predictions: list[dict]) -> list[dict]:
    """Identify high/low tide events as local maxima/minima in the series.

    Each prediction is {"t": ISO, "v": float}. Returns the same shape with
    an added "type" field of "H" or "L". An extremum is detected when the
    previous-vs-current sign of the difference flips. Edge values (first/
    last samples) are skipped because we cannot classify them.
    """
    if len(predictions) < 3:
        return []
    extrema: list[dict] = []
    for i in range(1, len(predictions) - 1):
        prev_v = predictions[i - 1]["v"]
        cur_v = predictions[i]["v"]
        next_v = predictions[i + 1]["v"]
        if cur_v > prev_v and cur_v >= next_v:
            extrema.append({"t": predictions[i]["t"], "type": "H", "v": cur_v})
        elif cur_v < prev_v and cur_v <= next_v:
            extrema.append({"t": predictions[i]["t"], "type": "L", "v": cur_v})
    return extrema


def _parse_noaa_predictions(response_json: dict) -> list[dict]:
    """Convert NOAA's {"predictions": [{"t": "YYYY-MM-DD HH:MM", "v": "1.234"}]} to floats.

    NOAA returns `t` as a naive timestamp string (no timezone suffix). With
    time_zone=gmt those are UTC; we serialize as ISO-8601 with a Z suffix
    so JS `new Date(t)` parses them unambiguously as UTC and auto-localizes
    for display. Without the Z, JS treats the naive string as local time,
    introducing the same ~7-8h shift bug we just fixed on the request side.
    """
    out: list[dict] = []
    for entry in response_json.get("predictions", []) or []:
        try:
            v = float(entry["v"])
        except (KeyError, ValueError, TypeError):
            continue
        t_raw = entry.get("t")
        if not t_raw:
            continue
        # "2026-05-22 06:00" → "2026-05-22T06:00:00Z"
        t_iso = t_raw.replace(" ", "T")
        if "T" in t_iso and t_iso.count(":") == 1:
            t_iso = t_iso + ":00"
        if not t_iso.endswith("Z"):
            t_iso = t_iso + "Z"
        out.append({"t": t_iso, "v": v})
    return out


def fetch_tides(lat: float, lon: float, *, _client: httpx.Client | None = None) -> dict | None:
    """Fetch tide predictions for the nearest CA NOAA station.

    Returns the standardized payload or None if the upstream call fails.
    Cached per station_id for 24 h.
    """
    station_id, station_name, station_distance_km = nearest_station(lat, lon)

    now = time.time()
    cached = _CACHE.get(station_id)
    if cached and cached.expires_at > now:
        return cached.payload

    # NOAA CO-OPS interprets begin_date / end_date in the timezone specified
    # by time_zone. Previously we sent naive UTC strings paired with
    # time_zone=lst_ldt (local station time) — that's a ~7-8h shift bug:
    # NOAA reads "06:00" as 6 AM PDT (= 13:00 UTC), not 6 AM UTC. Result:
    # at midnight viewing, the past half of the client's ±8h window had no
    # cached data, so the chart curve only filled the right side.
    # Fix: time_zone=gmt with naive UTC strings. The response 't' fields
    # come back as UTC ISO timestamps. The frontend's `new Date(t)` parses
    # them as UTC and auto-localizes for display.
    nowUtc = datetime.now(timezone.utc).replace(tzinfo=None)
    begin = nowUtc - timedelta(hours=_PAST_PREDICTION_HOURS)
    end = nowUtc + timedelta(hours=_PREDICTION_HOURS)
    params = {
        "product": "predictions",
        "application": "Shorelife",
        "station": station_id,
        "begin_date": begin.strftime("%Y%m%d %H:%M"),
        "end_date": end.strftime("%Y%m%d %H:%M"),
        "datum": "MLLW",
        "time_zone": "gmt",
        "units": "english",
        "interval": "h",  # hourly resolution; sufficient for chart + extrema
        "format": "json",
    }

    client = _client or httpx.Client(headers={"User-Agent": "Shorelife/1.0"})
    owns_client = _client is None
    try:
        try:
            response = client.get(_NOAA_DATAGETTER, params=params, timeout=20.0)
        except Exception:
            return None
        if response.status_code != 200:
            return None
        try:
            response_json = response.json()
        except ValueError:
            return None
    finally:
        if owns_client:
            client.close()

    predictions = _parse_noaa_predictions(response_json)
    if not predictions:
        return None

    payload = {
        "station_id": station_id,
        "station_name": station_name,
        "station_distance_km": round(station_distance_km, 2),
        "predictions": predictions,
        "extrema": detect_extrema(predictions),
    }
    _CACHE[station_id] = _CacheEntry(expires_at=now + _CACHE_TTL_SECONDS, payload=payload)
    return payload
