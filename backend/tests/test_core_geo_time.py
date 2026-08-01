"""Guards for the two shared primitives extracted from 8 duplicate definitions.

``haversine_km`` had four copies in three algebraically distinct forms;
``forecast_cutoff_utc`` had four byte-identical copies of the 5 AM PT rule that
keeps same-morning data out of a feature predicting that morning's sample.
"""

import math
from datetime import date

import pytest

from app.core.geo import haversine_km, nearest_by_haversine
from app.core.timewindows import forecast_cutoff_utc


def _asin_form(lat1, lon1, lat2, lon2):
    """The `services.tides` formulation this replaced."""
    r = 6371.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def test_haversine_matches_the_formulations_it_replaced():
    """Consolidating the three forms must be numerically free at CA scales."""
    pairs = [
        (32.7, -117.2, 32.8, -117.3),
        (37.8, -122.5, 34.0, -118.5),
        (41.7, -124.2, 32.5, -117.1),
    ]
    for p in pairs:
        assert haversine_km(*p) == pytest.approx(_asin_form(*p), abs=1e-9)


def test_haversine_known_distance():
    # SF Ocean Beach -> Santa Monica: ~417 km of latitude and ~360 km of
    # longitude at 36N, so ~552 km great-circle.
    km = haversine_km(37.7597, -122.5107, 34.0094, -118.4973)
    assert 545 < km < 560


def test_haversine_zero_and_symmetry():
    assert haversine_km(33.0, -118.0, 33.0, -118.0) == 0.0
    assert haversine_km(33.0, -118.0, 34.0, -119.0) == pytest.approx(
        haversine_km(34.0, -119.0, 33.0, -118.0)
    )


def test_nearest_picks_closest_and_reports_distance():
    candidates = [("far", 40.0, -124.0), ("near", 33.01, -118.01), ("mid", 34.0, -119.0)]
    key, km = nearest_by_haversine(33.0, -118.0, candidates)
    assert key == "near"
    assert km < 2.0


def test_nearest_respects_an_explicit_cap_and_never_guesses_one():
    candidates = [("far", 40.0, -124.0)]
    assert nearest_by_haversine(33.0, -118.0, candidates, max_km=10) is None
    # Without a cap the far station is still the nearest — the scans this
    # replaced disagreed about whether to apply one, so it must be explicit.
    assert nearest_by_haversine(33.0, -118.0, candidates)[0] == "far"


def test_nearest_handles_empty_and_null_coordinates():
    assert nearest_by_haversine(33.0, -118.0, []) is None
    assert nearest_by_haversine(33.0, -118.0, [("x", None, None)]) is None


def test_nearest_keeps_a_falsy_station_key():
    """`cli.py`'s scan guarded with `if nearest:`, which would drop a station_id
    of "" or 0. The shared version tests `is None`."""
    got = nearest_by_haversine(33.0, -118.0, [("", 33.01, -118.01)])
    assert got is not None and got[0] == ""


def test_forecast_cutoff_is_5am_pacific_across_the_dst_boundary():
    """PDT (UTC-7) in summer, PST (UTC-8) in winter — the whole reason this is
    not a hardcoded UTC hour."""
    summer = forecast_cutoff_utc(date(2026, 7, 15))
    winter = forecast_cutoff_utc(date(2026, 1, 15))
    assert summer.hour == 12, "5 AM PDT is 12:00 UTC"
    assert winter.hour == 13, "5 AM PST is 13:00 UTC"
    assert str(summer.tz) == "UTC" and str(winter.tz) == "UTC"


def test_forecast_cutoff_is_monotonic_by_date():
    a = forecast_cutoff_utc(date(2026, 3, 1))
    b = forecast_cutoff_utc(date(2026, 3, 2))
    assert b > a
