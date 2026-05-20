"""Per-beach shore-normal compass bearing (degrees, pointing OUT TO SEA).

Reimplementation of the algorithm in
`app.data.pipeline.marine_microbiology.compute_beach_shore_azimuth` that works
on a flat list of (beach_id, lat, lon) tuples — the shape the API has at
request time — instead of a pandas DataFrame.

Algorithm
---------
For each beach:
  1. Find the K=5 nearest neighbors (squared-degree distance is fine for
     sorting).
  2. Convert their offsets to local meters (lat-scaled).
  3. Total-least-squares (SVD) fit through the centered cloud → coastline
     tangent vector.
  4. Two perpendiculars are candidate normals. Pick the one whose dot product
     with the vector toward the CA inland centroid (37°N, 120.5°W) is
     NEGATIVE — that's the seaward direction.
  5. Convert the chosen vector to compass bearing (0°=N, clockwise).

This is the *seaward* (offshore) normal — i.e. wind blowing FROM this
bearing is an onshore wind hitting the beach. The marine-microbiology
pipeline stores the ONSHORE (inland-pointing) version of this same axis;
the two differ by exactly 180°.

The compute is ~1 ms per beach. Results are cached in a module-scope dict
keyed by beach_id (value never changes for a given station).
"""
from __future__ import annotations

from threading import Lock

import numpy as np

# Approximate California inland centroid (Sacramento Valley). Same constants
# as the offline pipeline so the two paths agree to within float precision.
_INLAND_LAT = 37.0
_INLAND_LON = -120.5
_K_NEIGHBORS = 5
_FALLBACK_SEAWARD_DEG = 270.0  # west — sane default for most of the CA coast

_CACHE: dict[str, float] = {}
_LOCK = Lock()


def _compute_seaward_bearing(
    target_lat: float,
    target_lon: float,
    neighbor_lats: np.ndarray,
    neighbor_lons: np.ndarray,
) -> float:
    """SVD fit + sign-flip toward sea. Returns compass degrees [0, 360)."""
    if len(neighbor_lats) < 2:
        return _FALLBACK_SEAWARD_DEG

    lat_scale = 110_540.0
    lon_scale = 111_320.0 * np.cos(np.deg2rad(target_lat))

    x_m = (neighbor_lons - target_lon) * lon_scale
    y_m = (neighbor_lats - target_lat) * lat_scale
    xy = np.column_stack([x_m, y_m])
    xy = xy - xy.mean(axis=0)

    try:
        _, _, vt = np.linalg.svd(xy, full_matrices=False)
        tangent = vt[0]
    except np.linalg.LinAlgError:
        return _FALLBACK_SEAWARD_DEG

    n_a = np.array([-tangent[1], tangent[0]])
    n_b = -n_a

    inland_x = (_INLAND_LON - target_lon) * lon_scale
    inland_y = (_INLAND_LAT - target_lat) * lat_scale
    inland = np.array([inland_x, inland_y])

    # Seaward = the perpendicular pointing AWAY from the inland centroid.
    seaward = n_a if np.dot(n_a, inland) < 0 else n_b

    bearing = (np.rad2deg(np.arctan2(seaward[0], seaward[1])) + 360.0) % 360.0
    return float(bearing)


def compute_shore_normal_deg(
    beach_id: str,
    beaches: list[tuple[str, float, float]],
) -> float | None:
    """Return the compass bearing pointing FROM `beach_id` OUT TO SEA.

    `beaches` is the full population of (id, lat, lon) — used to find the
    K nearest neighbors. Result is cached forever in a module-scope dict;
    the value depends only on geography, which doesn't change between
    process restarts.

    Returns None if the target beach is not in `beaches` or has bad coords.
    """
    cached = _CACHE.get(beach_id)
    if cached is not None:
        return cached

    target: tuple[float, float] | None = None
    ids: list[str] = []
    lats: list[float] = []
    lons: list[float] = []
    for bid, lat, lon in beaches:
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(lat_f) and np.isfinite(lon_f)):
            continue
        ids.append(bid)
        lats.append(lat_f)
        lons.append(lon_f)
        if bid == beach_id:
            target = (lat_f, lon_f)

    if target is None or len(ids) < 2:
        return None

    lat_arr = np.asarray(lats, dtype=float)
    lon_arr = np.asarray(lons, dtype=float)
    target_lat, target_lon = target

    d2 = (lat_arr - target_lat) ** 2 + (lon_arr - target_lon) ** 2
    order = np.argsort(d2)
    # Skip self (distance 0) and take the next K.
    neighbor_idx = [i for i in order if ids[i] != beach_id][:_K_NEIGHBORS]
    if len(neighbor_idx) < 2:
        return None

    bearing = _compute_seaward_bearing(
        target_lat,
        target_lon,
        lat_arr[neighbor_idx],
        lon_arr[neighbor_idx],
    )
    with _LOCK:
        _CACHE[beach_id] = bearing
    return bearing


def clear_cache() -> None:
    """Drop all cached bearings — only useful in tests."""
    with _LOCK:
        _CACHE.clear()
