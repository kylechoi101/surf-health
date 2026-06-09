"""Serve precomputed hourly forecast payloads from ``hourly_forecast.parquet``.

The ``/beaches/{id}/hourly`` route reads this first and only falls back to a live
Open-Meteo call when a beach's 0.1° grid cell isn't present. Built by
``app.data.pipeline.hourly_forecast``. The parquet is reloaded when its mtime
changes (the daily snapshot swap), so a long-lived process picks up fresh data
without a restart.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

_PARQUET_NAME = "hourly_forecast.parquet"

_cache: dict[tuple[float, float], dict] = {}
_loaded_mtime: float | None = None
_loaded_path: Path | None = None


def _load(path: Path) -> None:
    global _cache, _loaded_mtime, _loaded_path
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _cache = {}
        _loaded_mtime = None
        _loaded_path = path
        return
    if path == _loaded_path and mtime == _loaded_mtime and _cache:
        return
    df = pd.read_parquet(path)
    cache: dict[tuple[float, float], dict] = {}
    for row in df.itertuples(index=False):
        try:
            cache[(round(float(row.lat_r), 1), round(float(row.lon_r), 1))] = json.loads(row.payload_json)
        except (ValueError, TypeError):
            continue
    _cache = cache
    _loaded_mtime = mtime
    _loaded_path = path


def get_precomputed_hourly(curated_dir: Path, lat: float, lon: float) -> dict | None:
    """Return the precomputed hourly payload for the cell containing (lat, lon),
    or None if the parquet is missing or the cell isn't covered."""
    path = Path(curated_dir) / _PARQUET_NAME
    if not path.exists():
        return None
    _load(path)
    return _cache.get((round(float(lat), 1), round(float(lon), 1)))
