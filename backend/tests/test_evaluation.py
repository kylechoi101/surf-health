import numpy as np
import pandas as pd

from app.ml.evaluation import (
    classification_metrics,
    holdout_frame,
    persist_holdout_predictions,
    sensitivity_at_specificity,
    sensitivity_at_specificity_record,
)


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


def test_sensitivity_at_specificity_hand_computed_at_0_87():
    # 8 negatives, 8 positives. The Searcy benchmark target specificity is 0.87.
    # With 8 negatives, spec >= 0.87 allows at most 1 false positive (7/8 = 0.875
    # >= 0.87; 6/8 = 0.75 < 0.87). Exactly one negative (0.62) scores into the
    # positive cloud; the other seven score below every positive.
    negatives = np.array([0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.62])
    positives = np.array([0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.95])
    labels = np.concatenate([np.zeros(8, dtype=int), np.ones(8, dtype=int)])
    probs = np.concatenate([negatives, positives])
    result = sensitivity_at_specificity(labels, probs, target_specificity=0.87)
    # Best operating point clearing spec >= 0.87: threshold 0.55 (the lowest
    # positive score) accepts the single 0.62 false positive (spec 7/8 = 0.875,
    # still >= 0.87) and captures ALL 8 positives -> sensitivity 1.0. The rule
    # maximizes sensitivity among thresholds that clear the specificity bar, so it
    # prefers this over the spec-1.0 / sens-0.75 threshold at 0.65.
    assert result["specificity"] >= 0.87
    assert abs(result["sensitivity"] - 1.0) < 1e-9
    assert abs(result["specificity"] - 0.875) < 1e-9
    assert abs(result["threshold"] - 0.55) < 1e-9


def test_sensitivity_at_specificity_record_is_json_safe():
    # Healthy two-class input -> finite floats.
    labels = np.array([0, 0, 1, 1])
    probs = np.array([0.1, 0.2, 0.7, 0.9])
    record = sensitivity_at_specificity_record(labels, probs, target_specificity=0.87)
    assert set(record) == {"sensitivity", "specificity", "threshold"}
    assert all(isinstance(v, float) for v in record.values())

    # Degenerate single-class -> None (NaN coerced), so json.dumps won't emit NaN.
    import json

    degenerate = sensitivity_at_specificity_record(np.array([1, 1, 1]), np.array([0.4, 0.6, 0.8]))
    assert degenerate["sensitivity"] is None
    assert degenerate["specificity"] is None
    # Must serialize cleanly (no bare NaN token).
    assert "NaN" not in json.dumps(degenerate)


def test_holdout_frame_columns_and_broadcast():
    labels = np.array([0, 1, 0, 1])
    probs = np.array([0.1, 0.8, 0.3, 0.9])
    frame = holdout_frame(labels, probs, model="ensemble", group=["a", "a", "b", "b"])
    assert list(frame.columns) == ["label", "probability", "model", "group"]
    assert frame["label"].tolist() == [0, 1, 0, 1]
    assert frame["model"].tolist() == ["ensemble"] * 4  # scalar broadcast
    assert frame["group"].tolist() == ["a", "a", "b", "b"]
    assert frame["label"].dtype.kind == "i"
    # None-valued id columns are dropped, not added as a NaN column.
    frame2 = holdout_frame(labels, probs, date=None)
    assert "date" not in frame2.columns


def test_holdout_frame_length_mismatch_raises():
    import pytest

    with pytest.raises(ValueError):
        holdout_frame(np.array([0, 1]), np.array([0.1, 0.2, 0.3]))
    with pytest.raises(ValueError):
        holdout_frame(np.array([0, 1]), np.array([0.1, 0.2]), group=["only-one"])


def test_persist_holdout_predictions_round_trip(tmp_path):
    labels = np.array([0, 1, 1, 0, 1])
    probs = np.array([0.12, 0.71, 0.88, 0.33, 0.65])
    out = persist_holdout_predictions(
        tmp_path / "holdout.parquet",
        labels,
        probs,
        model="xgb_undersample_ensemble",
        county=["LA", "LA", "SD", "SD", "OC"],
    )
    assert out is not None
    assert out.exists()
    loaded = pd.read_parquet(out)
    assert {"label", "probability", "model", "county"}.issubset(loaded.columns)
    assert loaded["label"].tolist() == [0, 1, 1, 0, 1]
    np.testing.assert_allclose(loaded["probability"].to_numpy(), probs)
    assert loaded["county"].tolist() == ["LA", "LA", "SD", "SD", "OC"]
    # The persisted pairs can recompute the Searcy operating point with no retrain.
    record = sensitivity_at_specificity_record(
        loaded["label"].to_numpy(), loaded["probability"].to_numpy(), 0.87
    )
    assert record["sensitivity"] is not None


def test_persist_holdout_predictions_empty_is_skipped(tmp_path):
    out = persist_holdout_predictions(tmp_path / "empty.parquet", np.array([]), np.array([]))
    assert out is None
    assert not (tmp_path / "empty.parquet").exists()
