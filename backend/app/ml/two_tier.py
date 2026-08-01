"""Level + deviation (two-tier) modelling primitives.

The shipped single-tier model is, in the regime it actually serves, close to a
per-beach lookup table: within-beach AUROC ~0.50 on served forecasts (it cannot
tell a bad day from a normal day at the same beach) because its skill comes from
recent-outcome autocorrelation that is stale on ~95% of served rows. See
``model_truth.md`` (2026-07-23 audit).

Validated locally 2026-07-23 (scratchpad ``validate_plan2.py``, real 193-feature
pipeline + the repo's own ``stale_evaluation`` censoring): on the served (stale)
regime, **staleness-augmented training + a per-beach baseline offset**

  * fixes the low-side "defaults to safe when stale" bias  (-0.102 -> +0.004),
  * recovers served-regime AUCPR                            ( 0.535 -> 0.668),
  * beats the per-beach lookup floor on Brier              ( 0.085 vs 0.094),

at ~no cost to the fresh-sample regime (AUCPR 0.706 -> 0.696, Brier improves).

This module holds the three reusable primitives that produce those wins:
  * ``beach_baseline_margin`` — the 'level' tier, an XGBoost ``base_margin`` offset.
  * ``staleness_augmented_frame`` — the 'serve-regime' training data.
  * ``within_beach_auroc`` (+ ``_by_lag``) — the primary metric global AUCPR is blind to.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from app.ml.calibration import LOGIT_EPSILON, logit
from app.ml.stale_evaluation import RECENCY_COLUMN, censor_bacteria_history_for_cutoff

# Median served ``sample_age_days`` (model_truth.md Test 3). Rows censored to this
# age approximate the between-sample day the product actually publishes.
DEFAULT_STALE_CUTOFF_DAYS = 14
# Third copy of the probability->log-odds clip, now sourced from calibration.
# Provably a no-op here: these probabilities are empirical-Bayes shrunk rates,
# so they are bounded well away from the rails — measured across 669 beaches on
# the 1095-day window they span [0.0045, 0.9647], and the global rate is 0.178.
# Neither 1e-6 nor 1e-4 binds on a single beach, so the deployed offset model's
# base_margin is bit-identical before and after.
_EPS = LOGIT_EPSILON
_logit = logit


def beach_baseline_margin(
    labels,
    beach_ids,
    *,
    prior_strength: float = 4.0,
) -> tuple[dict[object, float], float]:
    """Per-beach shrunk exceedance log-odds — the 'level' tier / model offset.

    Empirical-Bayes shrink of each beach's exceedance rate toward the global rate
    (same form as ``SmoothedRatePrior`` / ``build_stale_prior_router`` already in
    the repo), returned as a logit so it drops straight into XGBoost as a fixed
    ``base_margin``. With the level supplied as an offset, the model on top can
    only reduce loss by explaining *within-beach* departures from that level —
    which is exactly the skill the single-tier model fails to learn.

    Returns ``(per_beach_margin, global_margin)``; unseen beaches use the global.
    """
    y = np.asarray(labels, dtype=float)
    b = np.asarray(beach_ids, dtype=object)
    if len(y) == 0:
        return {}, 0.0
    global_rate = float(np.clip(y.mean(), _EPS, 1.0 - _EPS))
    agg = pd.DataFrame({"b": b, "y": y}).groupby("b")["y"].agg(["sum", "count"])
    rate = (agg["sum"] + prior_strength * global_rate) / (agg["count"] + prior_strength)
    margins = {beach: float(_logit(r)) for beach, r in rate.items()}
    return margins, float(_logit(global_rate))


def margins_for(beach_ids, margins: dict[object, float], global_margin: float) -> np.ndarray:
    """Look up the per-row base_margin for a set of beaches (global fallback)."""
    return np.array(
        [margins.get(beach, global_margin) for beach in np.asarray(beach_ids, dtype=object)],
        dtype=float,
    )


def staleness_augmented_frame(
    features: pd.DataFrame,
    *,
    cutoff_days: int | float = DEFAULT_STALE_CUTOFF_DAYS,
    recency_column: str = RECENCY_COLUMN,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Stack fresh rows with a censored ('served-day') copy of themselves.

    The fresh copy is the sample-day the model trains on today; the censored copy
    zeros the bacteria-history (anchor) features and forces recency >= cutoff via
    the repo's own ``censor_bacteria_history_for_cutoff`` — the between-sample day
    the product will actually serve. Training on both teaches the model to fall
    back on the non-decaying covariates when the anchor is stale, instead of
    defaulting to "safe".

    Returns ``(augmented_features, is_stale_mask)`` aligned row-for-row.
    """
    fresh = features.reset_index(drop=True)
    stale = censor_bacteria_history_for_cutoff(fresh, cutoff_days=cutoff_days)
    augmented = pd.concat([fresh, stale], ignore_index=True)
    is_stale = np.concatenate(
        [np.zeros(len(fresh), dtype=bool), np.ones(len(stale), dtype=bool)]
    )
    return augmented, is_stale


def within_beach_auroc(
    labels,
    probabilities,
    beach_ids,
    *,
    min_samples: int = 20,
) -> tuple[float, int, int]:
    """Row-weighted mean of per-beach AUROC — the primary two-tier metric.

    Asks: at a *fixed* beach, can the model rank its exceedance days above its
    clean days? 0.5 means no daily skill — the model is a per-beach constant
    (a lookup table) and its apparent global skill is entirely between-beach.
    Global AUCPR/AUROC cannot see this failure because they are dominated by
    between-beach variance; this is the one number that can.

    Beaches with < ``min_samples`` rows or a single outcome class are skipped.
    Returns ``(auroc, n_beaches, n_rows)``; ``(nan, 0, 0)`` if none qualify.
    """
    frame = pd.DataFrame(
        {
            "y": np.asarray(labels, dtype=int),
            "p": np.asarray(probabilities, dtype=float),
            "b": np.asarray(beach_ids, dtype=object),
        }
    )
    weights: list[int] = []
    scores: list[float] = []
    for _, group in frame.groupby("b", sort=False):
        if len(group) < min_samples or group["y"].nunique() < 2:
            continue
        weights.append(len(group))
        scores.append(roc_auc_score(group["y"], group["p"]))
    if not weights:
        return float("nan"), 0, 0
    weight_arr = np.asarray(weights, dtype=float)
    return float(np.average(scores, weights=weight_arr)), len(weights), int(weight_arr.sum())


_DEFAULT_LAG_BINS = ((0, 3), (4, 7), (8, 14), (15, 30), (31, 90))


def within_beach_auroc_by_lag(
    labels,
    probabilities,
    beach_ids,
    lags,
    *,
    bins: tuple[tuple[int, int], ...] = _DEFAULT_LAG_BINS,
    min_samples: int = 15,
    min_rows_per_bin: int = 50,
) -> dict[str, dict[str, float]]:
    """``within_beach_auroc`` stratified by staleness (days since last sample).

    The served regime is lag >= 4d; this exposes whether within-beach skill
    survives it or collapses (the deployed model holds ~0.66 at lag 4-7 and is
    unmeasurably sparse beyond, which is precisely the train/serve gap).
    """
    labels = np.asarray(labels)
    probabilities = np.asarray(probabilities, dtype=float)
    beach_ids = np.asarray(beach_ids, dtype=object)
    lag_values = pd.to_numeric(pd.Series(lags), errors="coerce").to_numpy()
    out: dict[str, dict[str, float]] = {}
    for lo, hi in bins:
        mask = (lag_values >= lo) & (lag_values <= hi)
        if int(mask.sum()) < min_rows_per_bin:
            continue
        auroc, n_beaches, n_rows = within_beach_auroc(
            labels[mask], probabilities[mask], beach_ids[mask], min_samples=min_samples
        )
        out[f"lag_{lo}_{hi}d"] = {
            "within_beach_auroc": auroc,
            "n_beaches": float(n_beaches),
            "n_rows": float(n_rows),
        }
    return out
