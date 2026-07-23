from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

import numpy as np
import pandas as pd

from app.ml.calibration import risk_band
from app.ml.weather_delta import is_bacteria_history_feature


RECENCY_COLUMN = "days_since_enterococcus_value_obs"


def _validated_cutoff(cutoff_days: int | float) -> float:
    cutoff = float(cutoff_days)
    if cutoff <= 0:
        raise ValueError("cutoff_days must be positive")
    return cutoff


def stale_cutoff_label(cutoff_days: int | float) -> str:
    cutoff = int(_validated_cutoff(cutoff_days))
    return f"censored_{cutoff}d"


def stale_row_label(cutoff_days: int | float) -> str:
    cutoff = int(_validated_cutoff(cutoff_days))
    return f"stale_{cutoff}d"


def stale_row_mask(
    frame: pd.DataFrame,
    *,
    cutoff_days: int | float,
    recency_column: str = RECENCY_COLUMN,
) -> pd.Series:
    if recency_column not in frame.columns:
        raise ValueError(f"Missing required column '{recency_column}'")
    cutoff = _validated_cutoff(cutoff_days)
    recency = pd.to_numeric(frame[recency_column], errors="coerce")
    return recency.ge(cutoff).fillna(False)


def filter_stale_rows(
    frame: pd.DataFrame,
    *,
    cutoff_days: int | float,
    recency_column: str = RECENCY_COLUMN,
) -> pd.DataFrame:
    return frame.loc[
        stale_row_mask(frame, cutoff_days=cutoff_days, recency_column=recency_column)
    ].copy()


def censor_bacteria_history_for_cutoff(
    features: pd.DataFrame,
    *,
    cutoff_days: int | float,
) -> pd.DataFrame:
    cutoff = _validated_cutoff(cutoff_days)

    censored = features.copy()
    for column in censored.columns:
        if column == RECENCY_COLUMN:
            numeric = pd.to_numeric(censored[column], errors="coerce")
            censored[column] = np.maximum(numeric.fillna(cutoff).to_numpy(dtype=float), cutoff)
        elif is_bacteria_history_feature(column):
            censored[column] = 0.0
    return censored


# Serving sample-age distribution used to age the augmented rows. Sourced from
# the 2026-07-23 reliability audit (model_truth.md, Test 3): served forecasts
# carry a last-sample age of min 4 / median 9 / mean 15 / max 37 days, with 95%
# in the 8-44 day "middle band". Drawing augmented ages across that band makes
# the training recency distribution match what the product actually serves.
SERVING_SAMPLE_AGE_DAYS: tuple[int, ...] = (7, 9, 11, 14, 18, 21, 28, 35, 44)


def augment_training_with_staleness(
    features: pd.DataFrame,
    labels: np.ndarray,
    *,
    fraction: float = 1.0,
    sample_ages: Sequence[int | float] = SERVING_SAMPLE_AGE_DAYS,
    recency_column: str = RECENCY_COLUMN,
    random_state: int | np.random.Generator | None = None,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Append stale-censored duplicate rows to a *training* feature/label set.

    The model's strongest signal is the lagged bacteria-history features (rolling
    geomeans + last-observed value). They are fresh on every sample-day training
    row but stale on ~95% of served forecasts (median 9-day-old last sample).
    Trained only on fresh rows, the model over-relies on that signal and, when it
    is absent at serve time, defaults to "safe" — the low-side bias documented in
    model_truth.md Tests 4/5.

    This augmentation duplicates a ``fraction`` of the rows with their
    bacteria-history features zeroed (via :func:`censor_bacteria_history_for_cutoff`,
    the same transform the serve-time stale path applies) and their recency
    feature set to an age drawn from ``sample_ages``. Labels are preserved, so
    each duplicate teaches "with no recent risk signal and a sample this old, this
    environment still produced this outcome" — forcing the model onto the daily
    environmental drivers and a recency-aware base rate instead of defaulting
    safe. The original fresh rows are kept unchanged, so the sample-day regime is
    still learned and ``days_since_enterococcus_value_obs`` becomes an informative
    conditioning feature.

    Returns the concatenated ``(features, labels)`` for the caller to fit on. Only
    ever call this on rows destined for training — never on validation, test, or
    spatial-holdout rows, or the augmented duplicates leak synthetic rows into
    evaluation.
    """
    labels_arr = np.asarray(labels)
    if recency_column not in features.columns:
        return features, labels_arr
    n = len(features)
    if n == 0 or fraction <= 0.0:
        return features, labels_arr

    rng = (
        random_state
        if isinstance(random_state, np.random.Generator)
        else np.random.default_rng(random_state)
    )
    k = min(int(round(n * min(float(fraction), 1.0))), n)
    if k <= 0:
        return features, labels_arr

    pick = np.arange(n) if k >= n else rng.choice(n, size=k, replace=False)
    ages = np.asarray(sample_ages, dtype=float)
    if ages.size == 0:
        return features, labels_arr

    censored = censor_bacteria_history_for_cutoff(
        features.iloc[pick], cutoff_days=float(ages.min())
    )
    censored[recency_column] = rng.choice(ages, size=k, replace=True)

    augmented_features = pd.concat([features, censored], ignore_index=True)
    augmented_labels = np.concatenate([labels_arr, labels_arr[pick]])
    return augmented_features, augmented_labels


def build_stale_censoring_variants(
    features: pd.DataFrame,
    *,
    cutoffs: Iterable[int | float],
) -> dict[str, pd.DataFrame]:
    return {
        stale_cutoff_label(cutoff): censor_bacteria_history_for_cutoff(
            features,
            cutoff_days=cutoff,
        )
        for cutoff in cutoffs
    }


def build_serving_stale_sample_set(
    beaches: pd.DataFrame,
    observations: pd.DataFrame,
    *,
    forecasts: pd.DataFrame | None = None,
    reference_date: str | date | pd.Timestamp,
    stale_cutoff_days: int | float,
    min_samples: int = 100,
    min_positives: int = 10,
) -> pd.DataFrame:
    required_beach_columns = {"beach_id", "latest_official_sample_at"}
    missing_beach_columns = required_beach_columns.difference(beaches.columns)
    if missing_beach_columns:
        raise ValueError(f"Missing beach columns: {sorted(missing_beach_columns)}")
    required_observation_columns = {"beach_id", "sample_date", "exceeds_stv"}
    missing_observation_columns = required_observation_columns.difference(observations.columns)
    if missing_observation_columns:
        raise ValueError(f"Missing observation columns: {sorted(missing_observation_columns)}")

    reference = pd.Timestamp(reference_date).normalize()
    cutoff = _validated_cutoff(stale_cutoff_days)

    observations = observations.copy()
    observations["sample_date"] = pd.to_datetime(observations["sample_date"], errors="coerce")
    observations["exceeds_stv"] = pd.to_numeric(observations["exceeds_stv"], errors="coerce").fillna(0.0)
    history = (
        observations.dropna(subset=["beach_id", "sample_date"])
        .groupby("beach_id", as_index=False)
        .agg(
            sample_count=("sample_date", "size"),
            positive_count=("exceeds_stv", "sum"),
            first_sample_date=("sample_date", "min"),
            latest_observation_date=("sample_date", "max"),
        )
    )

    candidates = beaches.merge(history, on="beach_id", how="left")
    latest_official = pd.to_datetime(candidates["latest_official_sample_at"], errors="coerce")
    latest_observed = pd.to_datetime(candidates["latest_observation_date"], errors="coerce")
    candidates["latest_sample_date"] = latest_official.fillna(latest_observed)
    candidates["days_since_latest_sample"] = (
        reference - candidates["latest_sample_date"].dt.normalize()
    ).dt.days
    candidates["sample_count"] = candidates["sample_count"].fillna(0).astype(int)
    candidates["positive_count"] = candidates["positive_count"].fillna(0).astype(int)
    candidates["stale_cutoff_days"] = int(cutoff)
    candidates["reference_date"] = reference.date().isoformat()
    candidates["stale_sample_eligible"] = (
        candidates["sample_count"].ge(int(min_samples))
        & candidates["positive_count"].ge(int(min_positives))
        & candidates["days_since_latest_sample"].ge(cutoff)
    )

    if forecasts is not None and not forecasts.empty:
        forecast_columns = [
            column
            for column in ["beach_id", "forecast_date", "risk_band", "p_exceed", "model_version"]
            if column in forecasts.columns
        ]
        forecast_frame = forecasts.loc[:, forecast_columns].drop_duplicates("beach_id")
        candidates = candidates.merge(forecast_frame, on="beach_id", how="left")
    candidates["forecast_available"] = candidates.get("forecast_date", pd.Series(index=candidates.index)).notna()

    preferred_columns = [
        "beach_id",
        "name",
        "county",
        "reference_date",
        "latest_sample_date",
        "days_since_latest_sample",
        "sample_count",
        "positive_count",
        "stale_cutoff_days",
        "stale_sample_eligible",
        "forecast_available",
        "forecast_date",
        "risk_band",
        "p_exceed",
        "model_version",
    ]
    columns = [column for column in preferred_columns if column in candidates.columns]
    result = candidates.loc[candidates["stale_sample_eligible"], columns].copy()
    return result.sort_values(
        ["days_since_latest_sample", "sample_count"],
        ascending=[False, False],
    ).reset_index(drop=True)


def build_stale_prior_router(
    candidates: pd.DataFrame,
    observations: pd.DataFrame,
    *,
    min_beach_samples: int = 100,
    min_beach_positives: int = 10,
    min_county_samples: int = 50,
    min_county_positives: int = 5,
    county_strength: float = 8.0,
    beach_strength: float = 4.0,
) -> pd.DataFrame:
    required_candidate_columns = {"beach_id", "county", "sample_count", "positive_count"}
    missing_candidate_columns = required_candidate_columns.difference(candidates.columns)
    if missing_candidate_columns:
        raise ValueError(f"Missing candidate columns: {sorted(missing_candidate_columns)}")
    required_observation_columns = {"beach_id", "county", "exceeds_stv"}
    missing_observation_columns = required_observation_columns.difference(observations.columns)
    if missing_observation_columns:
        raise ValueError(f"Missing observation columns: {sorted(missing_observation_columns)}")

    result = candidates.copy()
    history = observations.dropna(subset=["beach_id"]).copy()
    history["exceeds_stv"] = pd.to_numeric(history["exceeds_stv"], errors="coerce").fillna(0.0)
    labels = history["exceeds_stv"].clip(0.0, 1.0)
    global_rate = float(np.clip(labels.mean(), 1e-6, 1.0 - 1e-6)) if len(labels) else 0.5

    county_stats = (
        history.dropna(subset=["county"])
        .groupby("county", as_index=False)
        .agg(count=("exceeds_stv", "size"), positives=("exceeds_stv", "sum"))
    )
    county_rates: dict[str, float] = {}
    county_eligible: dict[str, bool] = {}
    for _, row in county_stats.iterrows():
        county = str(row["county"])
        count = float(row["count"])
        positives = float(row["positives"])
        rate = (positives + county_strength * global_rate) / (count + county_strength)
        county_rates[county] = float(np.clip(rate, 1e-6, 1.0 - 1e-6))
        county_eligible[county] = count >= min_county_samples and positives >= min_county_positives

    beach_stats = (
        history.groupby("beach_id", as_index=False)
        .agg(count=("exceeds_stv", "size"), positives=("exceeds_stv", "sum"), county=("county", "last"))
    )
    beach_rates: dict[str, float] = {}
    for _, row in beach_stats.iterrows():
        beach_id = str(row["beach_id"])
        county = str(row["county"]) if pd.notna(row["county"]) else None
        parent_rate = county_rates.get(county, global_rate)
        count = float(row["count"])
        positives = float(row["positives"])
        rate = (positives + beach_strength * parent_rate) / (count + beach_strength)
        beach_rates[beach_id] = float(np.clip(rate, 1e-6, 1.0 - 1e-6))

    routes: list[str] = []
    probabilities: list[float] = []
    bases: list[str] = []
    for _, row in result.iterrows():
        beach_id = str(row["beach_id"])
        county = str(row["county"]) if pd.notna(row["county"]) else None
        sample_count = int(row["sample_count"])
        positive_count = int(row["positive_count"])
        if (
            sample_count >= min_beach_samples
            and positive_count >= min_beach_positives
            and beach_id in beach_rates
        ):
            routes.append("beach_prior")
            probabilities.append(beach_rates[beach_id])
            bases.append("historical beach rate shrunk toward county/global priors")
        elif county is not None and county_eligible.get(county, False):
            routes.append("county_prior")
            probabilities.append(county_rates[county])
            bases.append("historical county rate shrunk toward global prior")
        else:
            routes.append("global_prior")
            probabilities.append(global_rate)
            bases.append("global historical exceedance rate")

    result["stale_route"] = routes
    result["stale_probability"] = probabilities
    result["stale_risk_band"] = [risk_band(probability) for probability in probabilities]
    result["stale_route_basis"] = bases
    result["failed_closed"] = True
    return result
