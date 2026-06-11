from __future__ import annotations

import numpy as np
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
