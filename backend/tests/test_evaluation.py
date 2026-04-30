import numpy as np

from app.ml.evaluation import classification_metrics


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
