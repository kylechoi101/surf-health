from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression


class ProbabilityCalibrator:
    def __init__(self) -> None:
        self.model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")

    def fit(self, probabilities: np.ndarray, labels: np.ndarray) -> "ProbabilityCalibrator":
        self.model.fit(probabilities, labels)
        return self

    def transform(self, probabilities: np.ndarray) -> np.ndarray:
        return self.model.predict(probabilities)


def risk_band(probability: float) -> str:
    if probability < 0.2:
        return "Low"
    if probability < 0.45:
        return "Moderate"
    if probability < 0.7:
        return "High"
    return "Very High"

