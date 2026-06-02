"""
Surf-spot aliases: rename Beachwatch stations to the names surfers actually use
(e.g. "12345" -> "Black's Beach") and attach the true break location for display.

The official `name`/`latitude`/`longitude` are preserved untouched — the bacteria
model and station joins depend on them. We add display-only columns:

  surf_name        — surfer name if a curated spot matched, else NA
  is_surf_spot     — bool
  surf_latitude    — curated break lat if matched, else the beach's own lat
  surf_longitude   — curated break lon if matched, else the beach's own lon

Each curated alias attaches to at most one beach (its nearest within max_match_km),
so a cluster of stations near one break isn't all renamed identically.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.data.pipeline.external_covariates import haversine_km

_DATA_DIR = Path(__file__).parent / "_static_data"
_DEFAULT_ALIASES_CSV = _DATA_DIR / "surf_spot_aliases.csv"

DEFAULT_MAX_MATCH_KM = 5.0


def load_surf_aliases(path: Path | None = None) -> pd.DataFrame:
    """Load the curated surf-spot alias table (surf_name, latitude, longitude, ...)."""
    return pd.read_csv(path or _DEFAULT_ALIASES_CSV)


def apply_surf_aliases(
    beaches: pd.DataFrame,
    aliases: pd.DataFrame | None = None,
    max_match_km: float = DEFAULT_MAX_MATCH_KM,
) -> pd.DataFrame:
    """Attach surf_name / is_surf_spot / surf_latitude / surf_longitude to beaches."""
    out = beaches.copy()
    if aliases is None:
        aliases = load_surf_aliases()

    out["surf_name"] = pd.array([pd.NA] * len(out), dtype="string")
    out["is_surf_spot"] = False
    out["surf_latitude"] = out["latitude"].astype("float64")
    out["surf_longitude"] = out["longitude"].astype("float64")

    valid = out["latitude"].notna() & out["longitude"].notna()
    if not valid.any() or aliases.empty:
        return out

    # For each alias, find its single nearest beach. If two aliases land on the
    # same beach, the closer alias keeps it.
    best_for_beach: dict[int, tuple[float, str, float, float]] = {}
    for _, spot in aliases.iterrows():
        slat, slon = float(spot["latitude"]), float(spot["longitude"])
        nearest_idx, nearest_d = None, float("inf")
        for idx in out.index[valid]:
            d = haversine_km(
                float(out.at[idx, "latitude"]), float(out.at[idx, "longitude"]), slat, slon
            )
            if d < nearest_d:
                nearest_idx, nearest_d = idx, d
        if nearest_idx is None or nearest_d > max_match_km:
            continue
        prev = best_for_beach.get(nearest_idx)
        if prev is None or nearest_d < prev[0]:
            best_for_beach[nearest_idx] = (nearest_d, str(spot["surf_name"]), slat, slon)

    for idx, (_, surf_name, slat, slon) in best_for_beach.items():
        out.at[idx, "surf_name"] = surf_name
        out.at[idx, "is_surf_spot"] = True
        out.at[idx, "surf_latitude"] = slat
        out.at[idx, "surf_longitude"] = slon

    return out
