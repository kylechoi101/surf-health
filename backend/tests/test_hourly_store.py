"""Tests for the precomputed hourly-forecast serving store."""
import json

import pandas as pd

from app.services import hourly_store
from app.services.hourly_store import get_precomputed_hourly


def _write(tmp_path, rows):
    pd.DataFrame(rows, columns=["lat_r", "lon_r", "payload_json"]).to_parquet(
        tmp_path / "hourly_forecast.parquet", index=False
    )
    # reset the module cache so each test reloads from its own file
    hourly_store._loaded_path = None
    hourly_store._loaded_mtime = None
    hourly_store._cache = {}


def test_returns_payload_for_cell_containing_coords(tmp_path):
    payload = {"time": ["2026-06-09T00:00"], "wave_height_m": [1.2]}
    _write(tmp_path, [{"lat_r": 32.7, "lon_r": -117.2, "payload_json": json.dumps(payload)}])
    # a beach at 32.73 / -117.18 rounds to the (32.7, -117.2) cell
    got = get_precomputed_hourly(tmp_path, 32.73, -117.18)
    assert got == payload


def test_returns_none_for_uncovered_cell(tmp_path):
    _write(tmp_path, [{"lat_r": 32.7, "lon_r": -117.2, "payload_json": json.dumps({"time": []})}])
    assert get_precomputed_hourly(tmp_path, 40.1, -124.0) is None


def test_returns_none_when_parquet_missing(tmp_path):
    hourly_store._loaded_path = None
    hourly_store._cache = {}
    assert get_precomputed_hourly(tmp_path, 32.7, -117.2) is None


def test_reloads_when_file_mtime_changes(tmp_path):
    _write(tmp_path, [{"lat_r": 34.4, "lon_r": -119.5, "payload_json": json.dumps({"v": 1})}])
    assert get_precomputed_hourly(tmp_path, 34.4, -119.5) == {"v": 1}
    # overwrite with new content (new mtime) — store must pick it up
    import time
    time.sleep(0.01)
    pd.DataFrame(
        [{"lat_r": 34.4, "lon_r": -119.5, "payload_json": json.dumps({"v": 2})}],
        columns=["lat_r", "lon_r", "payload_json"],
    ).to_parquet(tmp_path / "hourly_forecast.parquet", index=False)
    assert get_precomputed_hourly(tmp_path, 34.4, -119.5) == {"v": 2}
