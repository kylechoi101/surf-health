"""The model must not be able to work out WHERE a beach is.

Leave-one-county-out and leave-one-beach-out backtests are the only evidence
this project has that the model learned transferable mechanism rather than a
per-place base-rate lookup. A feature that identifies location makes those
numbers meaningless: a model can score well on a held-out county purely by
recognising it and recalling its rate.

`latitude` and `longitude` were excluded by name for exactly this reason. That
was not enough. Measured on the shipped frame 2026-08-08, **19** location-identifying
columns were reaching a fitted model, via three routes:

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

# How far above the majority-class baseline a held-out-beach county prediction
# may sit. Anything more and the feature set is carrying position, whatever the
# per-feature correlations say.
_MAX_COUNTY_RECOVERY_LIFT = 0.25


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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN FAILING, recorded rather than hidden. Measured: county is "
        "recovered on held-out beaches at 0.955 against a 0.278 majority "
        "baseline, and held-out latitude to ~4 km. Cause is ~21 features that "
        "are CONSTANT within every beach and vary statewide (stormwater "
        "statics, watershed_area_km2, distance_to_gage_km, the pier/estuary "
        "proximities this change deliberately retained). Together they are a "
        "96%-unique per-beach fingerprint, so leave-one-BEACH-out remains a "
        "memorisation number even though leave-one-COUNTY-out is now clean "
        "(a genuinely unseen county cannot be placed: mean |error| 1.80 deg "
        "against a statewide sd of 1.71). Dropping them is a modelling "
        "decision with a real trade-off -- they cannot affect day-to-day "
        "discrimination, only a beach's baseline, so the cost to within-beach "
        "AUROC should be ~nil -- but it is not this PR's to make silently."
    ),
)
def test_county_cannot_be_recovered_from_features_on_held_out_beaches(
    beach_day_frame: pd.DataFrame,
) -> None:
    """The guard that asks the ACTUAL question instead of a proxy for it.

    Added after review demolished the correlation test's coverage claim. Two
    confirmed blind spots in `|rho| vs latitude`:

      * `coastal_x_km` is `longitude * cos(lat) * 111.32` -- a raw coordinate --
        but California's coast runs north-south, so it scores only 0.47 against
        LATITUDE and sails under the threshold. Deleting it from the denylist
        left all correlation/support tests green.
      * any NON-MONOTONE function of latitude (e.g. `abs(lat - 35)`) evades a
        rank correlation entirely.

    Correlation against one axis was always a proxy. The real question is
    whether a learner can recover WHERE a row is from the features the model
    gets, so ask that directly: fit a small tree on some beaches and predict the
    county of beaches it has never seen. Near-majority-baseline accuracy means
    the features do not carry location.
    """
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import GroupShuffleSplit

    enriched, raw = _enriched_sample(beach_day_frame)
    features = [
        c for c in _model_feature_columns(enriched)
        if pd.api.types.is_numeric_dtype(enriched[c])
    ]
    matrix = enriched[features].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    county = raw["county"].astype(str).to_numpy()
    groups = raw["beach_id"].astype(str).to_numpy()

    keep = county != "nan"
    matrix, county, groups = matrix[keep], county[keep], groups[keep]
    if len(np.unique(groups)) < 20:  # pragma: no cover - truncated frame
        pytest.skip("too few beaches to hold any out")

    train_idx, test_idx = next(
        GroupShuffleSplit(n_splits=1, test_size=0.3, random_state=0).split(
            matrix, county, groups
        )
    )
    model = RandomForestClassifier(
        n_estimators=60, max_depth=12, random_state=0, n_jobs=-1
    ).fit(matrix.iloc[train_idx], county[train_idx])

    accuracy = float((model.predict(matrix.iloc[test_idx]) == county[test_idx]).mean())
    values, counts = np.unique(county[test_idx], return_counts=True)
    majority = float(counts.max() / counts.sum())

    assert accuracy <= majority + _MAX_COUNTY_RECOVERY_LIFT, (
        f"county recovered on held-out beaches at {accuracy:.3f} against a "
        f"{majority:.3f} majority baseline -- the features still carry location"
    )


# The static per-beach block ranks unseen beaches' base rates at Spearman 0.386
# on this sample (0.422 over the full 1095d window). Retained deliberately --
# stormwater-outfall density really does predict dirty water, and generalising
# to unseen beaches is what distinguishes mechanism from memorisation. The
# ceiling is set well above the measured level: this test exists to catch a NEW
# static feature that turns a modest mechanistic prior into a base-rate lookup,
# not to relitigate the features already adjudicated in features.py.
_MAX_HELD_OUT_BASE_RATE_RECOVERY = 0.55


def test_static_block_does_not_pin_held_out_beach_base_rate(
    beach_day_frame: pd.DataFrame,
) -> None:
    """Per-column guards are blind to what the static features do JOINTLY.

    Every guard above asks about one column at a time -- its correlation with
    latitude, the number of counties it is nonzero in. Fourteen retained
    features pass both and are still per-beach constants, and together they
    fingerprint 96% of beaches uniquely.

    A unique fingerprint is not itself the `historical_advisory_count` leak: it
    cannot be looked up for a beach that was never trained on. The question that
    matters is whether it lets a learner PREDICT an unseen beach's exceedance
    rate, so ask that directly -- fit on some beaches' static vectors, rank the
    held-out ones. See the long note in `features.py` for why a nonzero answer
    is accepted here rather than excluded.
    """
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import KFold

    enriched, raw = _enriched_sample(beach_day_frame)
    numeric = [
        c for c in _model_feature_columns(enriched)
        if pd.api.types.is_numeric_dtype(enriched[c])
    ]
    frame = enriched[numeric].copy()
    frame["_beach"] = raw["beach_id"].astype(str).to_numpy()
    frame["_label"] = pd.to_numeric(raw["exceeds_stv"], errors="coerce").to_numpy()

    varies = frame.groupby("_beach")[numeric].nunique(dropna=False)
    static = [c for c in numeric if (varies[c] <= 1).all()]
    # Exclude the columns that are constant only because this beach has no
    # observations of them -- they are not geography, just missing data.
    static = [
        c for c in static
        if not c.startswith(("uv_index", "wind_speed_mps", "days_since_"))
    ]
    if len(static) < 3:  # pragma: no cover - truncated frame
        pytest.skip("too few static features to test jointly")

    vectors = frame.groupby("_beach")[static].first()
    vectors = vectors.loc[:, vectors.nunique(dropna=False) > 1]

    rates = frame.groupby("_beach")["_label"].agg(["mean", "size"])
    rates = rates[rates["size"] >= 15]
    if len(rates) < 50:  # pragma: no cover - truncated frame
        pytest.skip("too few well-sampled beaches")

    matrix = vectors.reindex(rates.index).fillna(-1.0)
    truth = rates["mean"].to_numpy()
    predicted = np.zeros(len(matrix))
    for train_idx, test_idx in KFold(5, shuffle=True, random_state=0).split(matrix):
        predicted[test_idx] = RandomForestRegressor(
            n_estimators=200, min_samples_leaf=3, random_state=0, n_jobs=-1
        ).fit(matrix.iloc[train_idx], truth[train_idx]).predict(matrix.iloc[test_idx])

    recovered = float(spearmanr(predicted, truth).statistic)
    assert recovered <= _MAX_HELD_OUT_BASE_RATE_RECOVERY, (
        f"static per-beach features rank held-out beaches' base rates at "
        f"Spearman {recovered:.3f} (ceiling {_MAX_HELD_OUT_BASE_RATE_RECOVERY}) "
        f"-- a new static feature has turned a mechanistic prior into a "
        f"per-beach base-rate lookup, and leave-one-beach-out no longer measures "
        f"what it claims to"
    )
