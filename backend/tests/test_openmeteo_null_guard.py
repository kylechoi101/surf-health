"""The all-null-variable guard, and the UV source that exists because of it.

Background: ``archive-api.open-meteo.com/v1/archive``
accepts ``uv_index`` in ``hourly``, answers **HTTP 200**, includes the key in the
payload, and fills it with ``null`` for every hour. Nothing raised, the column
cached as all-NaN, and ``uv_index_24h_max`` silently read as the shortwave proxy
for three months while the docs credited it as a real feature.

These tests pin the two halves of the fix:
  * requesting a variable this endpoint does not serve is a **hard failure**;
  * a thin/empty response is **not**, because that is what a transient outage and
    an out-of-range date both look like, and the daily job must survive them.
"""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.data.connectors import hydrology_sources as hs
from app.data.connectors.hydrology_sources import (
    UV_ARCHIVE_EARLIEST_DATE,
    AllNullVariableError,
    OpenMeteoHistoricalSolarWindConnector,
    OpenMeteoHistoricalUvConnector,
    _assert_no_all_null_variables,
)

HOURS = [f"2023-08-06T{h:02d}:00" for h in range(24)]


def _archive_payload(uv_all_null: bool = True) -> dict:
    """The literal shape archive-api returns when uv_index is requested."""
    return {
        "hourly": {
            "time": list(HOURS),
            "cloud_cover": [40.0] * 24,
            "shortwave_radiation": [0.0] * 6 + [500.0] * 12 + [0.0] * 6,
            "uv_index": [None] * 24 if uv_all_null else [3.0] * 24,
            "wind_speed_10m": [4.0] * 24,
            "wind_direction_10m": [270.0] * 24,
        }
    }


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Stands in for httpx.AsyncClient; always answers with one canned payload."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[dict] = []

    async def get(self, url, params=None, timeout=None):  # noqa: ANN001
        self.calls.append(params or {})
        return _FakeResponse(self.payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


# ── the regression this whole step exists to prevent ──────────────────────────


def test_readding_uv_index_to_the_archive_connector_raises_instead_of_caching_nulls(tmp_path: Path):
    """THE regression test. If someone puts uv_index back in HOURLY_VARS, this fails.

    Guards both halves of the original bug: the silent success, and the all-null
    parquet left behind on disk for every later reader to trust.
    """
    connector = OpenMeteoHistoricalSolarWindConnector()
    connector.HOURLY_VARS = (
        "cloud_cover",
        "shortwave_radiation",
        "uv_index",  # <- the mistake
        "wind_speed_10m",
        "wind_direction_10m",
    )
    client = _FakeClient(_archive_payload(uv_all_null=True))

    with pytest.raises(AllNullVariableError, match="uv_index"):
        asyncio.run(
            connector._fetch_coord(
                client, 33.9, -118.4, date(2023, 8, 6), date(2023, 8, 6), tmp_path
            )
        )
    assert list(tmp_path.glob("*.parquet")) == [], "an all-null column must never reach disk"


def test_shipped_archive_connector_does_not_request_uv_index():
    """The archive cannot serve UV; asking for it is what produced the null column."""
    assert "uv_index" not in OpenMeteoHistoricalSolarWindConnector.HOURLY_VARS
    for expected in ("cloud_cover", "shortwave_radiation", "wind_speed_10m", "wind_direction_10m"):
        assert expected in OpenMeteoHistoricalSolarWindConnector.HOURLY_VARS


def test_gather_reraises_rather_than_logging_the_config_bug(tmp_path: Path, monkeypatch):
    """asyncio.gather(return_exceptions=True) would otherwise swallow it into a log line."""
    connector = OpenMeteoHistoricalSolarWindConnector()
    connector.HOURLY_VARS = ("cloud_cover", "uv_index")
    monkeypatch.setattr(hs.httpx, "AsyncClient", lambda *a, **k: _FakeClient(_archive_payload()))

    with pytest.raises(AllNullVariableError):
        asyncio.run(
            connector.fetch_historical_solar_wind(
                [(33.9, -118.4)], date(2023, 8, 6), date(2023, 8, 6), tmp_path
            )
        )


def test_healthy_archive_response_still_caches(tmp_path: Path):
    connector = OpenMeteoHistoricalSolarWindConnector()
    client = _FakeClient(_archive_payload())
    df = asyncio.run(
        connector._fetch_coord(
            client, 33.9, -118.4, date(2023, 8, 6), date(2023, 8, 6), tmp_path
        )
    )
    assert len(df) == 24
    assert len(list(tmp_path.glob("*.parquet"))) == 1
    assert "uv_index" not in client.calls[0]["hourly"]


# ── the transient/never-available distinction ─────────────────────────────────


def test_thin_response_is_transient_not_a_bug():
    """Every requested variable null == an outage or an out-of-range date.

    Must not raise: the daily job would die on an upstream hiccup, and the UV
    connector legitimately sees this shape for dates before 2022-08-04.
    """
    hourly = {"time": list(HOURS), "cloud_cover": [None] * 24, "uv_index": [None] * 24}
    _assert_no_all_null_variables(hourly, ("cloud_cover", "uv_index"), context="test")


def test_empty_response_is_transient_not_a_bug():
    _assert_no_all_null_variables({"time": []}, ("cloud_cover",), context="test")
    _assert_no_all_null_variables({}, ("cloud_cover",), context="test")


def test_partially_populated_sibling_does_not_trip_the_guard():
    """A sibling below the 50% floor is itself degraded, so nothing is provable."""
    hourly = {
        "time": list(HOURS),
        "cloud_cover": [40.0] * 5 + [None] * 19,  # 21% — too thin to be a witness
        "uv_index": [None] * 24,
    }
    _assert_no_all_null_variables(hourly, ("cloud_cover", "uv_index"), context="test")


def test_escape_hatch_downgrades_to_a_log_line(monkeypatch):
    monkeypatch.setenv("OPENMETEO_ALLOW_NULL_VARS", "1")
    _assert_no_all_null_variables(
        _archive_payload()["hourly"],
        ("cloud_cover", "uv_index"),
        context="test",
    )


# ── the replacement UV source ─────────────────────────────────────────────────


def test_uv_connector_targets_the_air_quality_archive():
    connector = OpenMeteoHistoricalUvConnector()
    assert connector.BASE_URL == "https://air-quality-api.open-meteo.com/v1/air-quality"
    assert connector.HOURLY_VARS == ("uv_index",)
    # Pinned by probe on 2026-08-07; see the constant's docstring for the table.
    assert UV_ARCHIVE_EARLIEST_DATE == date(2022, 8, 4)


def test_uv_connector_uses_the_same_cache_conventions(tmp_path: Path):
    """0.1 degree rounding, per-(coord, range) key, atomic write — same as solar/wind."""
    payload = {"hourly": {"time": list(HOURS), "uv_index": [1.0] * 24}}
    connector = OpenMeteoHistoricalUvConnector()
    df = asyncio.run(
        connector._fetch_coord(
            _FakeClient(payload), 33.94, -118.42, date(2023, 8, 6), date(2023, 8, 6), tmp_path
        )
    )
    assert set(df["station_id"]) == {"33.9_-118.4"}
    written = list(tmp_path.glob("*.parquet"))
    assert [p.name for p in written] == ["openmeteo_uv_33.9_-118.4_2023-08-06_2023-08-06.parquet"]
    assert not list(tmp_path.glob("*.tmp")), "atomic write must leave no temp file behind"


def test_uv_connector_refuses_to_cache_an_all_null_response(tmp_path: Path):
    """Pre-2022-08-04 dates return exactly this. Skip, do not persist, do not raise."""
    payload = {"hourly": {"time": list(HOURS), "uv_index": [None] * 24}}
    df = asyncio.run(
        OpenMeteoHistoricalUvConnector()._fetch_coord(
            _FakeClient(payload), 33.9, -118.4, date(2022, 7, 1), date(2022, 7, 1), tmp_path
        )
    )
    assert df.empty
    assert list(tmp_path.glob("*.parquet")) == []


def test_uv_fetch_clamps_the_start_date_to_the_archive_epoch(tmp_path: Path, monkeypatch):
    payload = {"hourly": {"time": list(HOURS), "uv_index": [1.0] * 24}}
    client = _FakeClient(payload)
    monkeypatch.setattr(hs.httpx, "AsyncClient", lambda *a, **k: client)
    asyncio.run(
        OpenMeteoHistoricalUvConnector().fetch_historical_uv(
            [(33.9, -118.4)], date(2020, 1, 1), date(2023, 1, 1), tmp_path
        )
    )
    assert client.calls[0]["start_date"] == UV_ARCHIVE_EARLIEST_DATE.isoformat()

    # A range entirely before the epoch is skipped without a request.
    client.calls.clear()
    out = asyncio.run(
        OpenMeteoHistoricalUvConnector().fetch_historical_uv(
            [(33.9, -118.4)], date(2020, 1, 1), date(2021, 1, 1), tmp_path
        )
    )
    assert out.empty and client.calls == []


# ── the splice into the aggregation input ─────────────────────────────────────


def test_merge_uv_hourly_replaces_a_legacy_all_null_column():
    """Cache files written before this change carry the archive's null uv_index."""
    from app.data.pipeline.solar_wind import merge_uv_hourly

    times = pd.to_datetime(HOURS[:3], utc=True)
    sw = pd.DataFrame({
        "station_id": "33.9_-118.4",
        "time_utc": times,
        "uv_index": [None, None, None],  # the legacy all-null column
        "shortwave_radiation": [0.0, 500.0, 700.0],
    })
    uv = pd.DataFrame({
        "station_id": "33.9_-118.4",
        "time_utc": times,
        "uv_index": [0.0, 4.5, 7.1],
    })
    out = merge_uv_hourly(sw, uv)
    assert list(out.columns).count("uv_index") == 1, "no _x/_y suffix survivors"
    assert out["uv_index"].tolist() == [0.0, 4.5, 7.1]


def test_merge_uv_hourly_falls_back_cleanly_when_uv_is_unavailable():
    from app.data.pipeline.solar_wind import merge_uv_hourly

    sw = pd.DataFrame({
        "station_id": ["33.9_-118.4"],
        "time_utc": pd.to_datetime(["2023-08-06T00:00"], utc=True),
        "uv_index": [None],
        "shortwave_radiation": [500.0],
    })
    out = merge_uv_hourly(sw, pd.DataFrame())
    assert "uv_index" not in out.columns, "no UV feed -> aggregator falls to the shortwave proxy"
    assert len(out) == 1


# ── partial 24 h windows ──────────────────────────────────────────────────────


def _hourly_cell(start: str, hours: int) -> pd.DataFrame:
    times = pd.date_range(start, periods=hours, freq="h", tz="UTC")
    return pd.DataFrame({
        "station_id": "33.9_-118.4",
        "time_utc": times,
        "latitude": 33.9,
        "longitude": -118.4,
        "cloud_cover": 20.0,
        "shortwave_radiation": [300.0] * hours,
        "wind_speed_10m": 4.0,
        "wind_direction_10m": 270.0,
    })


def test_a_partial_24h_window_is_dropped_not_emitted_truncated():
    """The daily-pipeline corruption found on 2026-08-07.

    The incremental path refetches only the last 7 days and aggregates that slice
    alone, so the slice's first day has no preceding-evening hours. It used to be
    emitted anyway — an 83% understatement of shortwave that then WON the
    ``keep="last"`` merge against a correct stored value.
    """
    from app.data.pipeline.solar_wind import aggregate_solar_wind_windows

    full = aggregate_solar_wind_windows(_hourly_cell("2026-06-01T00:00", 24 * 8))
    sliced = aggregate_solar_wind_windows(_hourly_cell("2026-06-03T00:00", 24 * 5))

    first_full_day = sliced["sample_date"].min()
    assert first_full_day > pd.Timestamp("2026-06-03").date(), (
        "the slice's leading day has an incomplete window and must not be emitted"
    )
    # Every day the slice DOES emit must match the continuous-history aggregation.
    merged = full.merge(sliced, on=["station_id", "sample_date"], suffixes=("_full", "_slice"))
    assert len(merged) == len(sliced) > 0
    assert (merged["shortwave_24h_sum_full"] == merged["shortwave_24h_sum_slice"]).all()


def test_complete_windows_are_still_emitted():
    from app.data.pipeline.solar_wind import aggregate_solar_wind_windows

    out = aggregate_solar_wind_windows(_hourly_cell("2026-06-01T00:00", 24 * 4))
    assert len(out) >= 2
    # 24 samples x 300 W/m2 x 3600 s / 1e6 = 25.92 MJ/m2
    assert out["shortwave_24h_sum"].round(2).eq(25.92).all()
