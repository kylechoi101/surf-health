from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import numpy as np
import pandas as pd

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
