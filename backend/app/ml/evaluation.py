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
