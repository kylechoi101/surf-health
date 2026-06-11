from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    mean_squared_error,
    precision_recall_curve,
)


_EPSILON = 1e-6


def _calibration_slope(labels: np.ndarray, probabilities: np.ndarray) -> float:
    if len(np.unique(labels)) < 2:
        return float("nan")
    clipped = np.clip(probabilities, _EPSILON, 1.0 - _EPSILON)
    logits = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000)
    model.fit(logits, labels.astype(int))
    return float(model.coef_[0][0])


def _precision_at_recall(
    labels: np.ndarray,
    probabilities: np.ndarray,
    target_recall: float = 0.8,
) -> float:
    precision, recall, _ = precision_recall_curve(labels, probabilities)
    eligible = precision[recall >= target_recall]
    if len(eligible) == 0:
        return 0.0
    return float(np.max(eligible))


def sensitivity_at_specificity(
    labels: np.ndarray,
    probabilities: np.ndarray,
    target_specificity: float = 0.87,
) -> dict[str, float]:
    """Sensitivity (recall on positives) at a fixed specificity operating point.

    Mirrors the operational benchmark used by public beach-warning systems, e.g.
    Searcy et al. 2018 ("Mining nowcast environmental data..."), which reports a
    median sensitivity of 0.50 at specificity 0.87 across 10 CA oceanic beaches.
    To compare honestly we must pick the decision threshold that delivers (at
    least) the target specificity, then read off the sensitivity there.

    Returns sensitivity, the achieved specificity, and the probability threshold.
    Sweeping the candidate thresholds (the unique predicted probabilities) we pick
    the threshold whose true-negative rate is closest to — but not below — the
    target; if none reaches the target (e.g. degenerate probabilities) we fall
    back to the threshold with the highest achievable specificity.

        specificity = TN / (TN + FP)        on the negatives
        sensitivity = TP / (TP + FN)        on the positives

    A "predict positive when p >= threshold" rule; ties at the threshold count as
    positive (so a very low threshold yields specificity 0, sensitivity 1).
    """
    labels = np.asarray(labels).astype(int)
    probabilities = np.asarray(probabilities, dtype=float)
    positives = labels == 1
    negatives = ~positives
    n_pos = int(positives.sum())
    n_neg = int(negatives.sum())
    if n_pos == 0 or n_neg == 0:
        return {
            "sensitivity": float("nan"),
            "specificity": float("nan"),
            "threshold": float("nan"),
        }

    # Candidate thresholds: one just above each distinct score, plus +inf (predict
    # all-negative -> specificity 1). Using distinct scores keeps this O(unique).
    candidates = np.unique(probabilities)
    thresholds = np.concatenate([candidates, [np.inf]])

    best_sens = 0.0
    best_spec = -1.0
    best_threshold = float("inf")
    # Track the highest specificity we ever see, as a fallback when the target is
    # unreachable (e.g. all negatives share the top score).
    fallback_sens = 0.0
    fallback_spec = -1.0
    fallback_threshold = float("inf")

    for threshold in thresholds:
        predicted_positive = probabilities >= threshold
        tp = int(np.sum(predicted_positive & positives))
        fp = int(np.sum(predicted_positive & negatives))
        specificity = (n_neg - fp) / n_neg
        sensitivity = tp / n_pos
        if specificity > fallback_spec or (
            specificity == fallback_spec and sensitivity > fallback_sens
        ):
            fallback_spec = specificity
            fallback_sens = sensitivity
            fallback_threshold = float(threshold)
        if specificity >= target_specificity and sensitivity >= best_sens:
            # Among thresholds that clear the target specificity, keep the one
            # with the highest sensitivity (the most useful warning rule).
            best_sens = sensitivity
            best_spec = specificity
            best_threshold = float(threshold)

    if best_spec < 0:
        # No threshold reached the target specificity; report the best attainable.
        return {
            "sensitivity": float(fallback_sens),
            "specificity": float(fallback_spec),
            "threshold": fallback_threshold,
        }
    return {
        "sensitivity": float(best_sens),
        "specificity": float(best_spec),
        "threshold": best_threshold,
    }


def classification_metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    labels = np.asarray(labels)
    probabilities = np.asarray(probabilities, dtype=float)
    return {
        "aucpr": float(average_precision_score(labels, probabilities)),
        "brier": float(brier_score_loss(labels, probabilities)),
        "log_loss": float(log_loss(labels, np.clip(probabilities, _EPSILON, 1.0 - _EPSILON), labels=[0, 1])),
        "calibration_slope": _calibration_slope(labels, probabilities),
        "precision_at_80_recall": _precision_at_recall(labels, probabilities),
    }


def regression_metrics(labels: np.ndarray, predictions: np.ndarray) -> dict[str, float]:
    rmse = mean_squared_error(labels, predictions) ** 0.5
    return {"rmse": float(rmse)}


def holdout_frame(
    labels: np.ndarray,
    probabilities: np.ndarray,
    **id_columns: object,
) -> pd.DataFrame:
    """Build a tidy (label, probability [, identifier...]) holdout-prediction frame.

    This is the per-row artifact that lets us recompute *any* threshold-based
    operating point — sensitivity@specificity for the Searcy et al. 2018
    benchmark, precision@recall, a custom warning rule — without retraining the
    model. ``training.py`` concatenates these held-out arrays only to feed
    ``classification_metrics`` and then discards them; this helper turns them
    into a persistable frame so they survive.

    ``label`` is coerced to int and ``probability`` to float. Each keyword in
    ``id_columns`` becomes a column (e.g. ``model="xgb_undersample_ensemble"``,
    ``county=...``, ``beach_id=...``, ``date=...``); scalars are broadcast,
    array-likes must match the number of rows.
    """
    labels = np.asarray(labels)
    probabilities = np.asarray(probabilities, dtype=float)
    if labels.shape[0] != probabilities.shape[0]:
        raise ValueError(
            f"labels ({labels.shape[0]}) and probabilities "
            f"({probabilities.shape[0]}) must have the same length"
        )
    n_rows = labels.shape[0]
    data: dict[str, object] = {
        "label": labels.astype(int),
        "probability": probabilities,
    }
    for name, value in id_columns.items():
        if value is None:
            continue
        if np.isscalar(value) or isinstance(value, (str, bytes)):
            data[name] = [value] * n_rows
        else:
            arr = np.asarray(value)
            if arr.shape[0] != n_rows:
                raise ValueError(
                    f"id column '{name}' has length {arr.shape[0]} but expected {n_rows}"
                )
            data[name] = arr
    return pd.DataFrame(data)


def persist_holdout_predictions(
    path: str | Path,
    labels: np.ndarray,
    probabilities: np.ndarray,
    **id_columns: object,
) -> Path | None:
    """Write holdout (label, probability) pairs to ``path`` as parquet.

    Guarded so a missing/empty array never crashes a training run: returns
    ``None`` (and writes nothing) when there are no rows or the inputs are
    unusable, and ``Path`` on a successful write. Any unexpected error is
    swallowed and reported via return value rather than propagated, because
    persisting an evaluation artifact must never take down the model build.
    """
    try:
        if labels is None or probabilities is None:
            return None
        if len(labels) == 0 or len(probabilities) == 0:
            return None
        frame = holdout_frame(labels, probabilities, **id_columns)
        if frame.empty:
            return None
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(out, index=False)
        return out
    except Exception:  # pragma: no cover - defensive: artifact write must not crash training
        return None


def _json_safe_operating_point(point: dict[str, float]) -> dict[str, float | None]:
    """Convert a sensitivity_at_specificity() result to a JSON-safe dict.

    NaN (the degenerate single-class result) becomes ``None`` so it round-trips
    through ``json.dumps`` cleanly instead of serializing to a bare ``NaN`` token.
    """
    safe: dict[str, float | None] = {}
    for key, value in point.items():
        if value is None or (isinstance(value, float) and not np.isfinite(value)):
            safe[key] = None
        else:
            safe[key] = float(value)
    return safe


def sensitivity_at_specificity_record(
    labels: np.ndarray,
    probabilities: np.ndarray,
    target_specificity: float = 0.87,
) -> dict[str, float | None]:
    """sensitivity_at_specificity() wrapped to a JSON-safe payload.

    Convenience for embedding the Searcy-benchmark operating point into
    ``system_health.json``: same computation, but NaN -> None so the result is
    safe to serialize and store under e.g. ``production_metrics``.
    """
    return _json_safe_operating_point(
        sensitivity_at_specificity(labels, probabilities, target_specificity)
    )
