"""Tests for the holdout-prediction persistence wired into app.ml.training.

These exercise `_persist_holdout_artifacts` directly on synthetic (label,
probability) data — no model retrain — proving the metrics-honesty path:
temporal + spatial holdout pairs land on disk as parquet, and the Searcy
sensitivity@spec operating point is recorded into the metrics payload under
the production winner's base key (so it ships in system_health.json).
"""

import json

import numpy as np
import pandas as pd

from app.ml.training import (
    _HOLDOUT_SPATIAL_ARTIFACT,
    _HOLDOUT_TEMPORAL_ARTIFACT,
    _SENSITIVITY_AT_SPEC_KEY,
    _persist_holdout_artifacts,
)


def _synthetic_pairs(n=200, seed=0):
    rng = np.random.default_rng(seed)
    labels = rng.integers(0, 2, size=n)
    # Positives score higher on average so the operating point is informative.
    probs = np.clip(0.3 * labels + rng.normal(0.3, 0.2, size=n), 0.0, 1.0)
    return labels, probs


def test_persist_holdout_artifacts_temporal_and_spatial(tmp_path):
    winner = "xgb_undersample_ensemble"
    t_labels, t_probs = _synthetic_pairs(seed=1)
    c_labels, c_probs = _synthetic_pairs(seed=2)
    b_labels, b_probs = _synthetic_pairs(seed=3)

    sink = {
        (winner, "county"): {
            "labels": c_labels,
            "probabilities": c_probs,
            "groups": np.array(["LA"] * len(c_labels)),
        },
        (winner, "beach_id"): {
            "labels": b_labels,
            "probabilities": b_probs,
            "groups": np.array(["beach-1"] * len(b_labels)),
        },
    }
    metrics = {
        winner: {"aucpr": 0.5},
        f"spatial_county_{winner}": {"aucpr": 0.49},
        f"spatial_beach_{winner}": {"aucpr": 0.87},
    }
    dates = np.array(["2026-06-01"] * len(t_labels))

    _persist_holdout_artifacts(
        tmp_path,
        winner=winner,
        metrics=metrics,
        temporal_labels=t_labels,
        temporal_probs=t_probs,
        temporal_dates=dates,
        predictions_sink=sink,
    )

    # Temporal artifact round-trips with the expected columns.
    temporal = pd.read_parquet(tmp_path / _HOLDOUT_TEMPORAL_ARTIFACT)
    assert {"label", "probability", "model", "date"}.issubset(temporal.columns)
    assert len(temporal) == len(t_labels)
    assert (temporal["model"] == winner).all()

    # Spatial artifact holds both county and beach holdout rows, tagged by kind.
    spatial = pd.read_parquet(tmp_path / _HOLDOUT_SPATIAL_ARTIFACT)
    assert {"label", "probability", "model", "holdout_kind", "group"}.issubset(spatial.columns)
    assert set(spatial["holdout_kind"].unique()) == {"county", "beach_id"}
    assert len(spatial) == len(c_labels) + len(b_labels)

    # Sensitivity@spec recorded under the production winner's base key + spatial keys.
    assert _SENSITIVITY_AT_SPEC_KEY in metrics[winner]
    point = metrics[winner][_SENSITIVITY_AT_SPEC_KEY]
    assert set(point) == {"sensitivity", "specificity", "threshold"}
    assert point["specificity"] is None or point["specificity"] >= 0.87 - 1e-9
    assert _SENSITIVITY_AT_SPEC_KEY in metrics[f"spatial_county_{winner}"]
    assert _SENSITIVITY_AT_SPEC_KEY in metrics[f"spatial_beach_{winner}"]

    # The whole metrics payload must be JSON-serializable (it goes into
    # system_health.json) — no bare NaN tokens.
    dumped = json.dumps(metrics)
    assert "NaN" not in dumped


def test_persist_holdout_artifacts_missing_temporal_is_skipped(tmp_path):
    # No temporal pairs (e.g. winner with no captured eval probs) -> no temporal
    # file, no crash, and no sensitivity key injected.
    winner = "logistic_hierarchical"
    metrics = {winner: {"aucpr": 0.4}}
    _persist_holdout_artifacts(
        tmp_path,
        winner=winner,
        metrics=metrics,
        temporal_labels=None,
        temporal_probs=None,
        predictions_sink={},
    )
    assert not (tmp_path / _HOLDOUT_TEMPORAL_ARTIFACT).exists()
    assert not (tmp_path / _HOLDOUT_SPATIAL_ARTIFACT).exists()
    assert _SENSITIVITY_AT_SPEC_KEY not in metrics[winner]


def test_persist_holdout_artifacts_degenerate_single_class(tmp_path):
    # All-positive temporal slice: persistence still writes the pairs, but the
    # operating point is null (helper returns NaN -> None) and nothing raises.
    winner = "hist_gbm"
    labels = np.ones(20, dtype=int)
    probs = np.linspace(0.4, 0.9, 20)
    metrics = {winner: {"aucpr": 0.5}}
    _persist_holdout_artifacts(
        tmp_path,
        winner=winner,
        metrics=metrics,
        temporal_labels=labels,
        temporal_probs=probs,
        predictions_sink={},
    )
    # File is written (the pairs are still useful), metric is recorded as null.
    assert (tmp_path / _HOLDOUT_TEMPORAL_ARTIFACT).exists()
    point = metrics[winner][_SENSITIVITY_AT_SPEC_KEY]
    assert point["sensitivity"] is None
    assert point["specificity"] is None
    json.dumps(metrics)  # must not raise


def test_persist_holdout_artifacts_winner_base_key_mapping(tmp_path):
    # A hist_gbm variant winner maps to the "hist_gbm" metrics base key, and its
    # spatial pairs are keyed by the full variant name in the sink.
    winner = "hist_gbm_positive_persistence_guard"
    labels, probs = _synthetic_pairs(seed=7)
    sink = {
        (winner, "county"): {
            "labels": labels,
            "probabilities": probs,
            "groups": np.array(["OC"] * len(labels)),
        }
    }
    metrics = {
        "hist_gbm": {"aucpr": 0.5},
        "spatial_county_hist_gbm": {"aucpr": 0.48},
    }
    _persist_holdout_artifacts(
        tmp_path,
        winner=winner,
        metrics=metrics,
        temporal_labels=labels,
        temporal_probs=probs,
        predictions_sink=sink,
    )
    # Sensitivity recorded under the base key "hist_gbm", not the variant name.
    assert _SENSITIVITY_AT_SPEC_KEY in metrics["hist_gbm"]
    assert _SENSITIVITY_AT_SPEC_KEY in metrics["spatial_county_hist_gbm"]
    spatial = pd.read_parquet(tmp_path / _HOLDOUT_SPATIAL_ARTIFACT)
    assert (spatial["model"] == winner).all()
