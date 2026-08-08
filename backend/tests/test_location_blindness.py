"""The model must not be able to work out WHERE a beach is.

Leave-one-county-out and leave-one-beach-out backtests are the only evidence
this project has that the model learned transferable mechanism rather than a
per-place base-rate lookup. A feature that identifies location makes those
numbers meaningless: a model can score well on a held-out county purely by
recognising it and recalling its rate.

`latitude` and `longitude` were excluded by name for exactly this reason. That
was not enough. Measured on the shipped frame 2026-08-08, **14** location
identifying columns were reaching the model anyway, via two routes:

  * coordinate laundering -- `coastal_y_km` is `latitude * 110.57` and scores
    Spearman **1.0000** against latitude;
  * single-county support -- every Tijuana / transboundary feature is nonzero
    in exactly one county, so `!= 0` is a perfect San Diego indicator whatever
    the value denotes.

These tests are structural: the first pins the curated denylist, the second and
third re-derive the property from data so a NEW feature with either leak shape
fails without anyone remembering to update a list.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr

from app.data.pipeline.features import (
    LOCATION_GUARD_EXEMPT_COLUMNS,
    LOCATION_IDENTIFYING_COLUMNS,
    _model_feature_columns,
    add_temporal_features,
)

# A feature whose |Spearman| against latitude exceeds this is a coordinate in
# disguise. Kept well above the retained proximity features (dist_to_pier_km
# 0.29, dist_to_estuary_km 0.34) and well below the removed ones
# (dist_to_chronic_source_km 0.9968, coastal_y_km 1.0000, nearest_stream_gage_id
# 0.9853), so it separates the two populations by a wide margin rather than
# splitting a continuum.
#
# ⚠️ KNOWN RESIDUAL, deliberately above the line at 0.75-0.78:
# `enterococcus_value_lag_2` / `_lag_3`. Those are the beach's own past readings
# -- the model's core legitimate signal -- and they track latitude only because
# ddPCR copies counts (median ~2,501) and culture MPN (median ~10) share one
# numeric column, and ddPCR is San Diego, which is the south. It is the
# copies-vs-MPN unit mixing surfacing as apparent geography, NOT a location
# feature, so excluding them would gut the model to fix the wrong thing.
# The correct fix is to denominate value-derived features by each row's own
# action value (the normalisation Step 7 already applied to the day-collapse
# tiebreak); that is a substantive model change and belongs in its own PR with
# its own measurement. Until then this IS a residual indirect location signal in
# leave-one-county-out folds and should be stated as such, not hidden.
_MAX_ABS_LATITUDE_CORRELATION = 0.85

# Below this many distinct counties with a nonzero value, "nonzero" is itself a
# location indicator regardless of what the number means.
_MIN_COUNTIES_WITH_SUPPORT = 2


def _enriched_sample(beach_day: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Enriched features plus the aligned raw rows carrying latitude/county."""
    raw = beach_day[beach_day["sample_date"] >= "2025-06-01"].copy()
    if raw.empty:  # pragma: no cover - only if the frame is truncated
        pytest.skip("no recent rows in beach_day")
    return add_temporal_features(raw), raw


def test_curated_denylist_is_actually_applied(beach_day_frame: pd.DataFrame) -> None:
    """Every name on the denylist is absent from the model's feature list."""
    enriched, _ = _enriched_sample(beach_day_frame)
    features = set(_model_feature_columns(enriched))
    leaked = sorted(features & LOCATION_IDENTIFYING_COLUMNS)
    assert not leaked, f"location-identifying columns reached the model: {leaked}"


def test_no_model_feature_is_a_coordinate_in_disguise(
    beach_day_frame: pd.DataFrame,
) -> None:
    """Data-derived, so a NEW laundered coordinate fails without a list edit.

    This is the test that would have caught `coastal_y_km`: it was never on any
    denylist, and excluding `latitude` by name did nothing to stop it.
    """
    enriched, raw = _enriched_sample(beach_day_frame)
    latitude = pd.to_numeric(raw["latitude"], errors="coerce").to_numpy()

    offenders: list[tuple[str, float]] = []
    for column in _model_feature_columns(enriched):
        values = pd.to_numeric(enriched[column], errors="coerce").to_numpy()
        finite = np.isfinite(values) & np.isfinite(latitude)
        if finite.sum() < 100 or np.unique(values[finite]).size < 2:
            continue
        rho = spearmanr(values[finite], latitude[finite]).statistic
        if np.isfinite(rho) and abs(rho) > _MAX_ABS_LATITUDE_CORRELATION:
            offenders.append((column, float(abs(rho))))

    assert not offenders, (
        "feature(s) track latitude closely enough to identify location: "
        + ", ".join(f"{c} (|rho|={r:.4f})" for c, r in sorted(offenders))
    )


def test_no_model_feature_has_single_county_support(
    beach_day_frame: pd.DataFrame,
) -> None:
    """A feature populated in only one county is a county indicator.

    `south_alongshore_wind_ms` is the motivating case: alongshore wind is real
    physics and correlates with latitude at only 0.019, but it is computed for
    one region only, so a nonzero value says "San Diego" on its own.
    """
    enriched, raw = _enriched_sample(beach_day_frame)
    county = raw["county"].to_numpy()

    offenders: list[tuple[str, int]] = []
    for column in _model_feature_columns(enriched):
        if column in LOCATION_GUARD_EXEMPT_COLUMNS:
            continue
        values = pd.to_numeric(enriched[column], errors="coerce").to_numpy()
        nonzero = np.isfinite(values) & (values != 0)
        if nonzero.sum() < 100:
            continue  # too sparse to be a usable indicator either way
        counties = pd.unique(county[nonzero])
        counties = [c for c in counties if isinstance(c, str) and c]
        if len(counties) < _MIN_COUNTIES_WITH_SUPPORT:
            offenders.append((column, len(counties)))

    assert not offenders, (
        "feature(s) are populated in too few counties, so their presence "
        "identifies location: "
        + ", ".join(f"{c} ({n} county)" for c, n in sorted(offenders))
    )


def test_proximity_features_are_deliberately_retained(
    beach_day_frame: pd.DataFrame,
) -> None:
    """Guard against over-correction.

    Distance to a *type* of structure is mechanism, not location: piers and
    estuary mouths recur up and down the coast. Dropping them would be a
    different kind of error, so the retention is pinned too.
    """
    enriched, _ = _enriched_sample(beach_day_frame)
    features = set(_model_feature_columns(enriched))
    for retained in (
        "dist_to_pier_km",
        "dist_to_estuary_km",
        "is_near_pier",
        "is_near_estuary_mouth",
    ):
        if retained in enriched.columns:
            assert retained in features, f"{retained} should remain a feature"
