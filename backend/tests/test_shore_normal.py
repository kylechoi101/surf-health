"""Tests for app.services.shore_normal.

The seaward bearing is computed by SVD-fitting a coastline tangent through
the K=5 nearest beaches, taking the perpendicular, and selecting the
candidate that points AWAY from the California inland centroid (37 N,
-120.5 W). Synthetic geometries make the expected answer unambiguous.
"""
from __future__ import annotations

import pytest

from app.services import shore_normal
from app.services.shore_normal import compute_shore_normal_deg


@pytest.fixture(autouse=True)
def _reset_cache():
    shore_normal.clear_cache()
    yield
    shore_normal.clear_cache()


def _approx(actual: float | None, expected: float, tol: float = 5.0) -> bool:
    """Compass-aware approx equality (handles wrap at 360)."""
    if actual is None:
        return False
    diff = abs(actual - expected) % 360.0
    return diff <= tol or diff >= 360.0 - tol


def test_vertical_coastline_west_of_inland_faces_west():
    """N-S running coastline at lon=-122 (west of -120.5 centroid):
    seaward bearing should be west (~270 deg)."""
    beaches = [
        ("a", 36.0, -122.0),
        ("b", 36.5, -122.0),
        ("c", 37.0, -122.0),
        ("d", 37.5, -122.0),
        ("e", 38.0, -122.0),
    ]
    bearing = compute_shore_normal_deg("c", beaches)
    assert _approx(bearing, 270.0), f"expected ~270, got {bearing}"


def test_vertical_coastline_east_of_inland_faces_east():
    """N-S running coastline at lon=-119 (east of centroid): faces east (~90)."""
    beaches = [
        ("a", 36.0, -119.0),
        ("b", 36.5, -119.0),
        ("c", 37.0, -119.0),
        ("d", 37.5, -119.0),
        ("e", 38.0, -119.0),
    ]
    bearing = compute_shore_normal_deg("c", beaches)
    assert _approx(bearing, 90.0), f"expected ~90, got {bearing}"


def test_horizontal_coastline_south_of_inland_faces_south():
    """E-W running coastline at lat=34 (south of 37 N centroid): faces south
    (~180 deg) — this is the canonical Southern California south-facing
    beach orientation (e.g. Santa Monica Bay south shore, Long Beach)."""
    beaches = [
        ("a", 34.0, -121.0),
        ("b", 34.0, -120.5),
        ("c", 34.0, -120.0),
        ("d", 34.0, -119.5),
        ("e", 34.0, -119.0),
    ]
    bearing = compute_shore_normal_deg("c", beaches)
    assert _approx(bearing, 180.0), f"expected ~180, got {bearing}"


def test_horizontal_coastline_north_of_inland_faces_north():
    """E-W coastline at lat=40 (north of centroid): faces north (~0/360)."""
    beaches = [
        ("a", 40.0, -121.0),
        ("b", 40.0, -120.5),
        ("c", 40.0, -120.0),
        ("d", 40.0, -119.5),
        ("e", 40.0, -119.0),
    ]
    bearing = compute_shore_normal_deg("c", beaches)
    assert _approx(bearing, 0.0), f"expected ~0/360, got {bearing}"


def test_southern_california_cluster_faces_roughly_southwest():
    """Real Southern California cluster spanning ~140 km — California coast
    runs roughly NW-SE here so the seaward normal is roughly SW (~225 deg).
    A wider population ensures the 5-nearest-neighbor SVD sees the genuine
    coastline trend, not just a colinear sub-stretch."""
    beaches = [
        ("scripps-pier", 32.8662, -117.2571),
        ("manhattan-beach-pier", 33.8847, -118.4109),
        ("santa-monica-pier", 34.0083, -118.4988),
        ("venice-beach", 33.9850, -118.4695),
        ("redondo-beach-pier", 33.8447, -118.3923),
        ("hermosa-beach-pier", 33.8622, -118.4017),
        ("imperial-beach-pier", 32.5793, -117.1352),
        ("ocean-beach-pier", 32.7491, -117.2542),
        ("pacific-beach", 32.7948, -117.2553),
    ]
    bearing = compute_shore_normal_deg("manhattan-beach-pier", beaches)
    assert bearing is not None
    # SW ~ 225 deg; allow generous tolerance for real beach clusters.
    assert 200.0 <= bearing <= 260.0, (
        f"SoCal coast should face SW (200-260 deg), got {bearing}"
    )


def test_unknown_beach_returns_none():
    beaches = [("a", 34.0, -120.0), ("b", 34.0, -120.5)]
    assert compute_shore_normal_deg("nonexistent", beaches) is None


def test_result_is_cached():
    """Second call for the same beach_id returns the cached value without
    re-running the SVD (verified by mutating the input and seeing the
    cached value persist)."""
    beaches = [
        ("a", 36.0, -122.0),
        ("b", 36.5, -122.0),
        ("c", 37.0, -122.0),
        ("d", 37.5, -122.0),
        ("e", 38.0, -122.0),
    ]
    first = compute_shore_normal_deg("c", beaches)
    # Pass an empty list — the cache should still return the first answer.
    second = compute_shore_normal_deg("c", [])
    assert first == second
    assert second is not None


def test_bearing_in_zero_to_360_range():
    beaches = [
        ("a", 36.0, -122.0),
        ("b", 36.5, -122.0),
        ("c", 37.0, -122.0),
        ("d", 37.5, -122.0),
        ("e", 38.0, -122.0),
    ]
    bearing = compute_shore_normal_deg("c", beaches)
    assert bearing is not None
    assert 0.0 <= bearing < 360.0
