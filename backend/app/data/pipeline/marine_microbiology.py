"""
Marine-microbiology-informed features.

Three derived signals not present in upstream weather/hydrology data:

1. shore_normal_wind_ms  — projection of the daily-mean wind vector onto each
   beach's onshore-normal axis (computed from local coastline orientation).
   POSITIVE  → onshore wind, compresses freshwater plumes against the shore.
   NEGATIVE  → offshore wind, disperses plumes seaward.
   Hypothesis: onshore wind concentrates fecal indicator bacteria at the
   shoreline, raising STV-exceedance probability after rain events.

2. is_near_pier / is_near_estuary_mouth — static binary flags from a
   hand-curated list of CA point sources (loaded from a CSV in this module's
   directory). Captures decades of microbiology: pier-roosting gulls and
   estuary discharge are persistent enterococci sources independent of weather.

3. solar_inactivation_index — combines shortwave radiation with cloud cover.
   Higher = stronger UV inactivation of enterococci (T90 = 1–2 h under full
   sun vs. 24–48 h under heavy cloud).

Build flow:
   compute_beach_shore_azimuth(stations) → DataFrame[beach_id, shore_azimuth_deg]
   compute_beach_coastal_features(stations) → DataFrame[beach_id, is_near_pier, is_near_estuary_mouth, dist_to_pier_km, dist_to_estuary_km]
   build_marine_microbiology_daily(beach_solar_wind_daily, shore_az, coastal) → daily features keyed by (beach_id, sample_date)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.data.pipeline.external_covariates import haversine_km

_DATA_DIR = Path(__file__).parent / "_static_data"
_DEFAULT_PIERS_CSV = _DATA_DIR / "ca_piers.csv"
_DEFAULT_ESTUARIES_CSV = _DATA_DIR / "ca_estuary_mouths.csv"

_PIER_PROX_KM = 0.20  # 200 m — within gull-roost foraging plume
_ESTUARY_PROX_KM = 1.50  # 1.5 km — within typical estuary mouth discharge fan


# ──────────────────────────────────────────────────────────────────────────────
# Coastline azimuth — per-beach onshore-normal vector
# ──────────────────────────────────────────────────────────────────────────────

def compute_beach_shore_azimuth(stations: pd.DataFrame) -> pd.DataFrame:
    """
    For each beach, estimate the onshore-normal azimuth (degrees, 0=North,
    clockwise) by fitting a local coastline tangent through the K nearest
    beaches and rotating 90° toward the inland side.

    California's coast trends roughly NW (300°) to SE (120°), so the seaward
    direction is generally west (~270°) for most of the state — but specific
    sections (e.g. LA basin south-facing, Monterey Bay east-facing) need a
    per-beach computation.

    Heuristic: take the great-circle bearing through the 5 nearest neighbors
    sorted along latitude. The shore-normal is that bearing rotated 90°.
    Inland disambiguation: the rotation that points AWAY from the centroid of
    California's interior (~119°W, 37°N) is "seaward"; we want "onshore" so we
    invert it: onshore_dir = bearing + 90° if (centroid - beach) · normal > 0,
    else bearing - 90°.

    Returns DataFrame[beach_id, shore_azimuth_deg] where shore_azimuth_deg is
    the *onshore* direction (where wind blowing TOWARD the shore is coming
    FROM the ocean and going TOWARD this azimuth in inland direction).
    """
    if stations.empty or "latitude" not in stations.columns:
        return pd.DataFrame(columns=["beach_id", "shore_azimuth_deg"])

    coords = stations[["beach_id", "latitude", "longitude"]].dropna(
        subset=["latitude", "longitude"]
    ).copy()
    coords["latitude"] = pd.to_numeric(coords["latitude"], errors="coerce")
    coords["longitude"] = pd.to_numeric(coords["longitude"], errors="coerce")
    coords = coords.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
    if coords.empty:
        return pd.DataFrame(columns=["beach_id", "shore_azimuth_deg"])

    K = 5
    # Approximate inland centroid for California (Sacramento Valley)
    INLAND_LAT, INLAND_LON = 37.0, -120.5

    out_rows: list[dict] = []
    lats = coords["latitude"].to_numpy()
    lons = coords["longitude"].to_numpy()
    for i, row in coords.iterrows():
        # Squared distance proxy in lat/lon space — fine for sorting near neighbors
        d2 = (lats - row["latitude"]) ** 2 + (lons - row["longitude"]) ** 2
        idx = np.argsort(d2)[1:K + 1]  # skip self
        if len(idx) < 2:
            out_rows.append({"beach_id": row["beach_id"], "shore_azimuth_deg": 270.0})
            continue
        # Linear fit through neighbors: bearing of best-fit line
        ngh_lat = lats[idx]
        ngh_lon = lons[idx]
        # Convert to local meters using row's lat as scale
        x_m = (ngh_lon - row["longitude"]) * 111_320 * np.cos(np.deg2rad(row["latitude"]))
        y_m = (ngh_lat - row["latitude"]) * 110_540
        # Total least squares via SVD for direction insensitive to swap of (x,y)
        XY = np.column_stack([x_m, y_m])
        XY = XY - XY.mean(axis=0)
        try:
            _, _, Vt = np.linalg.svd(XY, full_matrices=False)
            tangent = Vt[0]  # principal axis
        except np.linalg.LinAlgError:
            out_rows.append({"beach_id": row["beach_id"], "shore_azimuth_deg": 270.0})
            continue

        # Two perpendicular candidates for shore-normal
        nA = np.array([-tangent[1], tangent[0]])
        nB = -nA
        # Inland vector (points from beach toward CA centroid)
        inland_x = (INLAND_LON - row["longitude"]) * 111_320 * np.cos(np.deg2rad(row["latitude"]))
        inland_y = (INLAND_LAT - row["latitude"]) * 110_540
        inland = np.array([inland_x, inland_y])
        # Choose the normal pointing inland — that's the "onshore" direction
        chosen = nA if np.dot(nA, inland) > 0 else nB
        # Convert vector to compass azimuth (0°=N, clockwise)
        azimuth = (np.rad2deg(np.arctan2(chosen[0], chosen[1])) + 360) % 360
        out_rows.append({"beach_id": row["beach_id"], "shore_azimuth_deg": float(azimuth)})

    return pd.DataFrame(out_rows)


# ──────────────────────────────────────────────────────────────────────────────
# Pier / estuary proximity flags
# ──────────────────────────────────────────────────────────────────────────────

def _load_static_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["name", "latitude", "longitude"])
    return pd.read_csv(path)


def compute_beach_coastal_features(
    stations: pd.DataFrame,
    piers_csv: Path | None = None,
    estuaries_csv: Path | None = None,
) -> pd.DataFrame:
    """
    For each beach, compute:
      dist_to_pier_km, is_near_pier (bool: dist ≤ _PIER_PROX_KM)
      dist_to_estuary_km, is_near_estuary_mouth (bool: dist ≤ _ESTUARY_PROX_KM)

    Static features — depend only on lat/lon, not on date.
    """
    if stations.empty:
        return pd.DataFrame(columns=[
            "beach_id", "dist_to_pier_km", "is_near_pier",
            "dist_to_estuary_km", "is_near_estuary_mouth",
        ])

    piers = _load_static_csv(piers_csv or _DEFAULT_PIERS_CSV)
    estuaries = _load_static_csv(estuaries_csv or _DEFAULT_ESTUARIES_CSV)

    coords = stations[["beach_id", "latitude", "longitude"]].dropna().copy()
    coords["latitude"] = pd.to_numeric(coords["latitude"], errors="coerce")
    coords["longitude"] = pd.to_numeric(coords["longitude"], errors="coerce")
    coords = coords.dropna()

    rows: list[dict] = []
    for _, b in coords.iterrows():
        d_pier = np.inf
        if not piers.empty:
            d_pier = float(min(
                haversine_km(float(b["latitude"]), float(b["longitude"]),
                             float(p["latitude"]), float(p["longitude"]))
                for _, p in piers.iterrows()
                if pd.notna(p.get("latitude")) and pd.notna(p.get("longitude"))
            ))
        d_est = np.inf
        if not estuaries.empty:
            d_est = float(min(
                haversine_km(float(b["latitude"]), float(b["longitude"]),
                             float(e["latitude"]), float(e["longitude"]))
                for _, e in estuaries.iterrows()
                if pd.notna(e.get("latitude")) and pd.notna(e.get("longitude"))
            ))
        rows.append({
            "beach_id": b["beach_id"],
            "dist_to_pier_km": d_pier if np.isfinite(d_pier) else np.nan,
            "is_near_pier": int(d_pier <= _PIER_PROX_KM) if np.isfinite(d_pier) else 0,
            "dist_to_estuary_km": d_est if np.isfinite(d_est) else np.nan,
            "is_near_estuary_mouth": int(d_est <= _ESTUARY_PROX_KM) if np.isfinite(d_est) else 0,
        })
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────────
# Daily marine-microbiology join
# ──────────────────────────────────────────────────────────────────────────────

def build_marine_microbiology_daily(
    beach_solar_wind_daily: pd.DataFrame,
    shore_azimuth: pd.DataFrame,
) -> pd.DataFrame:
    """
    Project the daily-mean wind vector onto each beach's onshore-normal axis to
    get shore_normal_wind_ms, and compute the solar_inactivation_index.

    Inputs:
      beach_solar_wind_daily — must contain beach_id, sample_date,
        wind_u_24h_mean, wind_v_24h_mean, shortwave_24h_sum, cloud_cover_24h_mean
      shore_azimuth — beach_id, shore_azimuth_deg

    Returns:
      beach_id, sample_date, shore_normal_wind_ms, solar_inactivation_index,
      cloud_cover_24h_mean, shortwave_24h_sum, uv_index_24h_max,
      wind_speed_24h_max, days_since_sunny
    """
    if beach_solar_wind_daily.empty:
        return pd.DataFrame(columns=[
            "beach_id", "sample_date",
            "shore_normal_wind_ms", "solar_inactivation_index",
            "cloud_cover_24h_mean", "shortwave_24h_sum", "uv_index_24h_max",
            "wind_speed_24h_max", "wind_direction_24h_mean", "days_since_sunny",
        ])

    df = beach_solar_wind_daily.merge(shore_azimuth, on="beach_id", how="left")
    az_rad = np.deg2rad(df["shore_azimuth_deg"].fillna(270.0))  # default west-facing

    # Onshore-normal unit vector (points inland from beach):
    # x-component (east) = sin(azimuth_rad)
    # y-component (north) = cos(azimuth_rad)
    n_x = np.sin(az_rad)
    n_y = np.cos(az_rad)
    df["shore_normal_wind_ms"] = df["wind_u_24h_mean"] * n_x + df["wind_v_24h_mean"] * n_y

    # Solar inactivation: shortwave radiation, suppressed by cloud cover
    cloud = df["cloud_cover_24h_mean"].clip(lower=0, upper=100).fillna(50.0)
    sw = df["shortwave_24h_sum"].fillna(0.0).clip(lower=0)
    df["solar_inactivation_index"] = sw * (1.0 - cloud / 100.0)

    keep = [
        "beach_id", "sample_date",
        "shore_normal_wind_ms", "solar_inactivation_index",
        "cloud_cover_24h_mean", "shortwave_24h_sum", "uv_index_24h_max",
        "wind_speed_24h_max", "wind_direction_24h_mean", "days_since_sunny",
    ]
    keep = [c for c in keep if c in df.columns]
    return df[keep].copy()
