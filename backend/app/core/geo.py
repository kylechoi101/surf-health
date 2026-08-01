"""Great-circle distance and nearest-station lookup.

Lives in ``core`` rather than ``data.pipeline`` so ``services/`` and ``scripts/``
can use it without importing the pipeline.

There were four copies of the distance function (``external_covariates``,
``stormwater``, ``forecast_weather``, ``services.tides``) written in three
algebraically distinct forms — atan2 half-versine, asin half-versine, and the
``0.5 - cos(dphi)/2`` variant. All used R = 6371.0 and agreed to ~1e-10 km, so
consolidating on the atan2 form is numerically free; it is preferred because the
cos-difference form loses precision at sub-metre separations.
"""

from __future__ import annotations

from math import atan2, cos, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * atan2(sqrt(a), sqrt(1 - a))


def nearest_by_haversine(
    lat: float,
    lon: float,
    candidates,
    *,
    max_km: float | None = None,
) -> tuple[object, float] | None:
    """Closest ``(key, lat, lon)`` candidate to a point, or None.

    ``max_km`` is an explicit opt-in cap: the hand-rolled scan loops this
    replaces disagreed on whether to apply one (``surf_spots`` capped, the
    pipeline's beach->grid-cell scans did not), so it must be passed rather than
    assumed. Returns ``(key, distance_km)``.
    """
    best_key: object = None
    best_km = float("inf")
    for key, cand_lat, cand_lon in candidates:
        if cand_lat is None or cand_lon is None:
            continue
        distance = haversine_km(lat, lon, float(cand_lat), float(cand_lon))
        if distance < best_km:
            best_km, best_key = distance, key
    # `is None`, not falsy: a station_id of "" or 0 is a legitimate key, and the
    # falsy check in the loop this replaces (cli.py `if nearest:`) dropped it.
    if best_key is None or (max_km is not None and best_km > max_km):
        return None
    return best_key, best_km
