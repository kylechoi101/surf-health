import numpy as np

from app.ml.evaluation import classification_metrics, sensitivity_at_specificity


def test_classification_metrics_include_calibration_and_operating_point():
    metrics = classification_metrics(
        np.array([0, 0, 1, 1]),
        np.array([0.05, 0.2, 0.7, 0.9]),
    )

    assert set(["aucpr", "brier", "log_loss", "calibration_slope", "precision_at_80_recall"]).issubset(
        metrics
    )
    assert metrics["log_loss"] > 0
    assert metrics["calibration_slope"] > 0
    assert 0 <= metrics["precision_at_80_recall"] <= 1


def test_sensitivity_at_specificity_perfect_separation():
    # Perfectly separable scores: every positive scores above every negative, so
    # there exists a threshold with both specificity 1.0 and sensitivity 1.0.
    labels = np.array([0, 0, 0, 1, 1, 1])
    probabilities = np.array([0.05, 0.1, 0.2, 0.7, 0.8, 0.9])
    result = sensitivity_at_specificity(labels, probabilities, target_specificity=0.87)
    assert result["specificity"] >= 0.87
    assert result["sensitivity"] == 1.0


def test_sensitivity_at_specificity_known_example():
    # 10 negatives, 10 positives. Threshold = 0.5:
    #   negatives [0.1..0.55]: one of them (0.55) is >= 0.5 -> FP=1 -> spec 9/10 = 0.9
    #   positives [0.45..0.95]: one of them (0.45) is < 0.5 -> TP=9 -> sens 9/10 = 0.9
    # 0.9 specificity clears the 0.87 target, and 0.9 is the best sensitivity
    # attainable at spec >= 0.87 here.
    negatives = np.array([0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45 - 1e-9, 0.5 - 1e-9, 0.55])
    positives = np.array([0.45, 0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95])
    labels = np.concatenate([np.zeros(10, dtype=int), np.ones(10, dtype=int)])
    probabilities = np.concatenate([negatives, positives])
    result = sensitivity_at_specificity(labels, probabilities, target_specificity=0.87)
    assert result["specificity"] >= 0.87
    # Best achievable sensitivity at spec >= 0.87 is 0.9 (one positive sits below
    # the threshold that excludes the high-scoring negative).
    assert abs(result["sensitivity"] - 0.9) < 1e-9


def test_sensitivity_at_specificity_monotone_in_target():
    # As the specificity bar rises, the attainable sensitivity must not increase.
    rng = np.random.default_rng(0)
    labels = rng.integers(0, 2, size=400)
    # Give positives a higher mean so the curve is informative, not random.
    probabilities = np.clip(0.3 * labels + rng.normal(0.3, 0.2, size=400), 0, 1)
    sens_low = sensitivity_at_specificity(labels, probabilities, target_specificity=0.70)["sensitivity"]
    sens_high = sensitivity_at_specificity(labels, probabilities, target_specificity=0.95)["sensitivity"]
    assert sens_low >= sens_high


def test_sensitivity_at_specificity_degenerate_single_class():
    result = sensitivity_at_specificity(np.array([1, 1, 1]), np.array([0.4, 0.6, 0.8]))
    assert np.isnan(result["sensitivity"])
    assert np.isnan(result["specificity"])
