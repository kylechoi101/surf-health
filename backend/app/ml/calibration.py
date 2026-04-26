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


# Thresholds calibrated for hist_gbm at ~11% base exceedance rate.
# "High" at 0.30 means the model estimates 3× the average beach's risk —
# not a certainty, but elevated enough to warrant caution.  "Very High"
# at 0.70 indicates genuinely extreme conditions (post-storm, CSO event,
# or active advisory near minimum-detection samples).
_LOW_THRESHOLD = 0.20
_HIGH_THRESHOLD = 0.30
_VERY_HIGH_THRESHOLD = 0.70

# Human-readable explanations shown in the app alongside each band.
RISK_BAND_DESCRIPTIONS: dict[str, str] = {
    "Low": "Water quality appears typical for this beach. Swim at your own discretion.",
    "Moderate": "Slightly elevated risk. Conditions may be less ideal; consider checking again before swimming.",
    "High": "Elevated risk — estimated exceedance probability is roughly 3× the average beach. Caution advised, especially for vulnerable groups.",
    "Very High": "High likelihood of unsafe bacteria levels. Swimming is not recommended until conditions improve.",
}


def risk_band(probability: float) -> str:
    if probability < _LOW_THRESHOLD:
        return "Low"
    if probability < _HIGH_THRESHOLD:
        return "Moderate"
    if probability < _VERY_HIGH_THRESHOLD:
        return "High"
    return "Very High"
