from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, mean_squared_error


def classification_metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    return {
        "aucpr": float(average_precision_score(labels, probabilities)),
        "brier": float(brier_score_loss(labels, probabilities)),
    }


def regression_metrics(labels: np.ndarray, predictions: np.ndarray) -> dict[str, float]:
    rmse = mean_squared_error(labels, predictions) ** 0.5
    return {"rmse": float(rmse)}

