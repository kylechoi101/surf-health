from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Iterable

import numpy as np
import pandas as pd


BACTERIA_HISTORY_PATTERNS = (
    re.compile(r"^enterococcus_value(?:_last_obs|_lag_\d+)?$"),
    re.compile(r"^days_since_enterococcus_value_obs$"),
    re.compile(r"^enterococcus_geomean_"),
    re.compile(r"^geomean_"),
    re.compile(r"^samples_in_geomean_"),
    re.compile(r"^log_enterococcus$"),
)


def is_bacteria_history_feature(column: str) -> bool:
    return any(pattern.search(column) for pattern in BACTERIA_HISTORY_PATTERNS)


def select_no_bacteria_features(features: pd.DataFrame) -> pd.DataFrame:
    keep_columns = [column for column in features.columns if not is_bacteria_history_feature(column)]
    return features.loc[:, keep_columns].copy()


@dataclass(frozen=True)
class SmoothedRatePrior:
    global_rate: float
    county_rates: dict[str, float]
    beach_rates: dict[str, float]

    def predict(self, metadata: pd.DataFrame) -> np.ndarray:
        probabilities: list[float] = []
        for _, row in metadata.iterrows():
            beach_id = str(row.get("beach_id")) if pd.notna(row.get("beach_id")) else None
            county = str(row.get("county")) if pd.notna(row.get("county")) else None
            if beach_id is not None and beach_id in self.beach_rates:
                probabilities.append(self.beach_rates[beach_id])
            elif county is not None and county in self.county_rates:
                probabilities.append(self.county_rates[county])
            else:
                probabilities.append(self.global_rate)
        return np.asarray(probabilities, dtype=float)


def fit_smoothed_rate_prior(
    labels: np.ndarray,
    metadata: pd.DataFrame,
    train_rows: np.ndarray,
    *,
    county_strength: float = 8.0,
    beach_strength: float = 4.0,
) -> SmoothedRatePrior:
    train_labels = np.asarray(labels, dtype=float)[train_rows]
    train_metadata = metadata.iloc[train_rows].reset_index(drop=True).copy()
    global_rate = float(np.clip(train_labels.mean(), 1e-6, 1.0 - 1e-6)) if len(train_labels) else 0.5
    train_frame = train_metadata.assign(label=train_labels)

    county_rates: dict[str, float] = {}
    for county, group in train_frame.dropna(subset=["county"]).groupby("county", sort=False):
        count = float(len(group))
        positives = float(group["label"].sum())
        rate = (positives + county_strength * global_rate) / (count + county_strength)
        county_rates[str(county)] = float(np.clip(rate, 1e-6, 1.0 - 1e-6))

    beach_rates: dict[str, float] = {}
    for beach_id, group in train_frame.dropna(subset=["beach_id"]).groupby("beach_id", sort=False):
        county = group["county"].dropna().astype(str).iloc[-1] if group["county"].notna().any() else None
        county_rate = county_rates.get(county, global_rate)
        count = float(len(group))
        positives = float(group["label"].sum())
        rate = (positives + beach_strength * county_rate) / (count + beach_strength)
        beach_rates[str(beach_id)] = float(np.clip(rate, 1e-6, 1.0 - 1e-6))

    return SmoothedRatePrior(
        global_rate=global_rate,
        county_rates=county_rates,
        beach_rates=beach_rates,
    )


def clip_weather_delta(
    weather_probabilities: np.ndarray,
    prior_probabilities: np.ndarray,
    *,
    max_delta: float,
) -> np.ndarray:
    weather = np.asarray(weather_probabilities, dtype=float)
    prior = np.asarray(prior_probabilities, dtype=float)
    delta = np.clip(weather - prior, -float(max_delta), float(max_delta))
    return np.clip(prior + delta, 0.0, 1.0)


def select_delta_cap(
    labels: np.ndarray,
    weather_probabilities: np.ndarray,
    prior_probabilities: np.ndarray,
    *,
    caps: Iterable[float],
) -> float:
    labels_array = np.asarray(labels, dtype=float)
    candidate_caps = [float(cap) for cap in caps]
    if not candidate_caps:
        return 0.0

    def score(cap: float) -> tuple[float, float]:
        clipped = clip_weather_delta(weather_probabilities, prior_probabilities, max_delta=cap)
        brier = float(np.mean((clipped - labels_array) ** 2))
        return brier, cap

    return min(candidate_caps, key=score)
