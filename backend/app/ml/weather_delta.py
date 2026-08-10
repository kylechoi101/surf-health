"""Bacteria-history feature detection + smoothed per-beach base-rate priors.

Originally the helper module for the `hist_gbm_no_bacteria_weather_delta`
candidate (an environment-only model blended toward a base-rate prior). That
model was removed 2026-07-22 — it was the worst candidate in the registry
(held-out county AUCPR 0.224 vs 0.437 persistence, calibration slope −0.577,
i.e. anti-correlated), and its daily backtest folds cost CI time on a job that
has timed out before. What survives is used elsewhere:

- ``is_bacteria_history_feature`` — the live stale-censoring path
  (`app/ml/stale_evaluation.py`), which zeroes risk-history features on
  between-sample serving rows.
- ``fit_smoothed_rate_prior`` — the offline spatial diagnostic
  (`scripts/diagnose_spatial_brier.py`) baseline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd


# Bacteria-history features are now built from `enterococcus_action_ratio`
# (value / that row's own action value) rather than the raw mixed-unit
# `enterococcus_value` — see docs/ACTION_VALUE_NORMALIZATION.md. Both spellings
# are matched: the raw-column patterns stay so a frame built by older code, or a
# persisted holdout artifact from before the change, is still censored correctly
# rather than leaking a bacteria-history feature into an environment-only view.
BACTERIA_HISTORY_PATTERNS = (
    re.compile(r"^enterococcus_action_ratio(?:_last_obs|_lag_\d+)?$"),
    re.compile(r"^enterococcus_value(?:_last_obs|_lag_\d+)?$"),
    re.compile(r"^days_since_enterococcus_(?:value|action_ratio)_obs$"),
    re.compile(r"^enterococcus_(?:action_ratio_)?geomean_"),
    re.compile(r"^geomean_"),
    re.compile(r"^samples_in_geomean_"),
    re.compile(r"^log_enterococcus$"),
)


def is_bacteria_history_feature(column: str) -> bool:
    return any(pattern.search(column) for pattern in BACTERIA_HISTORY_PATTERNS)


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
