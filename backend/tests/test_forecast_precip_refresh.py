"""Forecast-time precip/streamflow refresh on synthetic forecast candidates.

The forecast candidate rows are cloned from each beach's most-recent LAB sample,
which freezes the rainfall/streamflow windows at values 12-37 days stale by
forecast time. These tests prove the refresh in app.ml.training rewrites those
columns to the forecast-date values from precip_daily / streamflow_daily, using
the same beach->station match the curation pipeline uses, recomputes the derived
rain-policy flags from the refreshed base, and falls back to the frozen value
(without raising) when no station/date row matches.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from app.data.pipeline.stormwater import (
    INCH_TO_MM,
    RAIN_GENERAL_ADVISORY_INCHES,
    RAIN_MONITORING_PAUSE_INCHES,
)
from app.ml.training import (
    _candidate_nearest_precip_station,
    _refresh_candidate_precip_features,
    _refresh_candidate_streamflow_features,
)

_FORECAST = date(2026, 6, 11)
# Stale sample-day values the candidate was cloned with (a dry spell weeks ago).
_STALE = {
    "precip_mm_6h": 0.0,
    "precip_mm_24h": 0.0,
    "precip_mm_48h": 0.0,
    "precip_mm_72h": 0.0,
    "precip_mm_7d": 0.0,
    "precip_awi": 1.0,
    "first_flush_flag": 0.0,
    "first_rain_score": 0.0,
}


def _candidates() -> pd.DataFrame:
    rows = []
    for bid, lat, lon in (
        ("beach-a", 32.90, -117.25),
        ("beach-b", 33.65, -118.00),
    ):
        row = {
            "beach_id": bid,
            "latitude": lat,
            "longitude": lon,
            # frozen rain-policy flags (computed off the stale precip_mm_72h == 0)
            "rain_72h_inches": 0.0,
            "rain_72h_monitoring_pause_flag": 0,
            "rain_72h_general_advisory_flag": 0,
            # frozen streamflow
            "streamflow_cfs_latest": 1.0,
            "streamflow_cfs_mean_24h": 1.0,
            "streamflow_cfs_max_24h": 1.0,
            "streamflow_rising_flag": 0,
            **_STALE,
        }
        rows.append(row)
    return pd.DataFrame(rows)


def _precip_daily(stations: list[tuple[str, float, float]], wet: bool = True) -> pd.DataFrame:
    """One forecast-date row per station; ``wet`` flips on a soaking storm."""
    rows = []
    for sid, lat, lon in stations:
        rows.append({
            "station_id": sid,
            "latitude": lat,
            "longitude": lon,
            "sample_date": pd.Timestamp(_FORECAST),
            "precip_mm_6h": 8.0 if wet else 0.0,
            "precip_mm_24h": 20.0 if wet else 0.0,
            "precip_mm_48h": 28.0 if wet else 0.0,
            "precip_mm_72h": 30.0 if wet else 0.0,
            "precip_mm_7d": 35.0 if wet else 0.0,
            "precip_awi": 12.0 if wet else 1.0,
            "first_flush_flag": 1.0 if wet else 0.0,
            "first_rain_score": 0.8 if wet else 0.0,
        })
    return pd.DataFrame(rows)


def _links() -> pd.DataFrame:
    # Pour points right on the beaches; nearest_stream_gage_id maps to a gage.
    return pd.DataFrame([
        {
            "beach_id": "beach-a",
            "pour_point_latitude": 32.90,
            "pour_point_longitude": -117.25,
            "nearest_stream_gage_id": "gage-a",
        },
        {
            "beach_id": "beach-b",
            "pour_point_latitude": 33.65,
            "pour_point_longitude": -118.00,
            "nearest_stream_gage_id": "gage-b",
        },
    ])


def test_nearest_precip_station_uses_pour_point_haversine():
    candidates = _candidates()
    # Station A is closest to beach-a's pour point, station B to beach-b.
    precip = _precip_daily([("ST_A", 32.905, -117.255), ("ST_B", 33.66, -118.01)])
    mapping = _candidate_nearest_precip_station(candidates, precip, _links())
    assert mapping["beach-a"] == "ST_A"
    assert mapping["beach-b"] == "ST_B"


def test_precip_refresh_overwrites_stale_sample_day_values():
    candidates = _candidates()
    precip = _precip_daily([("ST_A", 32.905, -117.255), ("ST_B", 33.66, -118.01)], wet=True)
    _refresh_candidate_precip_features(candidates, precip, _links(), _FORECAST)

    # (a) Base precip columns took the forecast-date values, NOT the frozen 0s.
    for _, row in candidates.iterrows():
        assert row["precip_mm_72h"] == 30.0
        assert row["precip_mm_24h"] == 20.0
        assert row["precip_mm_7d"] == 35.0
        assert row["precip_awi"] == 12.0
        assert row["first_flush_flag"] == 1.0
        assert row["first_rain_score"] == 0.8


def test_precip_refresh_recomputes_rain_policy_flags_from_refreshed_base():
    candidates = _candidates()
    precip = _precip_daily([("ST_A", 32.905, -117.255), ("ST_B", 33.66, -118.01)], wet=True)
    _refresh_candidate_precip_features(candidates, precip, _links(), _FORECAST)

    # (b) 30 mm/72h is above both the monitoring-pause (0.1in) and general-advisory
    # (0.2in) thresholds, so BOTH flags flip on from their frozen 0.
    assert (candidates["rain_72h_monitoring_pause_flag"] == 1).all()
    assert (candidates["rain_72h_general_advisory_flag"] == 1).all()
    expected_inches = 30.0 / INCH_TO_MM
    assert np.allclose(candidates["rain_72h_inches"], expected_inches)
    # Sanity on the thresholds themselves (guards against a drift in stormwater.py).
    assert RAIN_MONITORING_PAUSE_INCHES * INCH_TO_MM <= 30.0
    assert RAIN_GENERAL_ADVISORY_INCHES * INCH_TO_MM <= 30.0


def test_precip_refresh_keeps_frozen_value_when_no_station_or_date_match():
    candidates = _candidates()
    before = candidates.copy(deep=True)

    # No precip rows for the forecast date (only a stale historical date) -> every
    # candidate keeps its frozen value and nothing raises.
    stale_precip = _precip_daily([("ST_A", 32.905, -117.255)], wet=True)
    stale_precip["sample_date"] = pd.Timestamp(date(2026, 5, 1))
    _refresh_candidate_precip_features(candidates, stale_precip, _links(), _FORECAST)
    pd.testing.assert_frame_equal(candidates, before)

    # Forecast-date rows exist but for a far-away station with no pour-point link:
    # beach with no resolvable station keeps frozen, no raise, others still refresh.
    candidates2 = _candidates()
    # Drop beach-b's link so it has only its own (far) coords; place the only
    # station near beach-a. beach-b still maps to ST_A (nearest) — so to force a
    # true no-match we give an empty links frame AND strip candidate coords.
    candidates2.loc[candidates2["beach_id"] == "beach-b", ["latitude", "longitude"]] = np.nan
    precip = _precip_daily([("ST_A", 32.905, -117.255)], wet=True)
    _refresh_candidate_precip_features(candidates2, precip, pd.DataFrame(), _FORECAST)
    a = candidates2[candidates2["beach_id"] == "beach-a"].iloc[0]
    b = candidates2[candidates2["beach_id"] == "beach-b"].iloc[0]
    assert a["precip_mm_72h"] == 30.0  # resolved + refreshed
    assert b["precip_mm_72h"] == 0.0   # unresolved -> frozen


def test_precip_refresh_no_op_on_empty_inputs():
    candidates = _candidates()
    before = candidates.copy(deep=True)
    _refresh_candidate_precip_features(candidates, pd.DataFrame(), _links(), _FORECAST)
    pd.testing.assert_frame_equal(candidates, before)
    # Empty candidates frame must not raise either.
    _refresh_candidate_precip_features(pd.DataFrame(), _precip_daily([("ST_A", 32.9, -117.25)]), _links(), _FORECAST)


def _streamflow_daily(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "gage_id": gid,
            "sample_date": pd.Timestamp(_FORECAST),
            "streamflow_cfs_latest": latest,
            "streamflow_cfs_mean_24h": latest * 0.8,
            "streamflow_cfs_max_24h": latest * 1.3,
            "streamflow_rising_flag": 1,
        }
        for gid, latest in rows
    ])


def test_streamflow_refresh_overwrites_via_nearest_gage_link():
    candidates = _candidates()
    sf = _streamflow_daily([("gage-a", 500.0), ("gage-b", 250.0)])
    _refresh_candidate_streamflow_features(candidates, sf, _links(), _FORECAST)
    a = candidates[candidates["beach_id"] == "beach-a"].iloc[0]
    b = candidates[candidates["beach_id"] == "beach-b"].iloc[0]
    assert a["streamflow_cfs_latest"] == 500.0
    assert a["streamflow_rising_flag"] == 1
    assert b["streamflow_cfs_latest"] == 250.0


def test_streamflow_refresh_keeps_frozen_when_no_match():
    candidates = _candidates()
    before = candidates.copy(deep=True)
    # No forecast-date streamflow rows -> frozen, no raise.
    sf = _streamflow_daily([("gage-a", 500.0)])
    sf["sample_date"] = pd.Timestamp(date(2026, 5, 1))
    _refresh_candidate_streamflow_features(candidates, sf, _links(), _FORECAST)
    pd.testing.assert_frame_equal(candidates, before)
