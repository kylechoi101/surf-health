"""Phase 0 wiring: within-beach diagnostics + beach_id/lag in holdout artifacts."""

import numpy as np
import pandas as pd

from app.ml.stale_evaluation import RECENCY_COLUMN
from app.ml.training import (
    _persist_and_diagnose_holdouts,
    _record_within_beach_diagnostics,
)


def _sink(labels, probs, beaches):
    return {
        ("xgb_undersample_ensemble", "beach_id"): {
            "labels": np.asarray(labels),
            "probabilities": np.asarray(probs, dtype=float),
            "groups": np.asarray(beaches, dtype=object),
        }
    }


def test_record_diagnostics_populates_temporal_and_spatial():
    # two beaches, perfect within-beach ranking -> within_beach_auroc == 1.0
    # (>= 20 rows/beach so both clear within_beach_auroc's min_samples default)
    labels = [0, 1, 0, 1] * 12
    probs = [0.1, 0.9, 0.2, 0.8] * 12
    beaches = (["a"] * 2 + ["b"] * 2) * 12
    lags = [6, 6, 9, 9] * 12
    metrics: dict = {}
    _record_within_beach_diagnostics(
        metrics,
        winner="xgb_undersample_ensemble",
        temporal_labels=np.asarray(labels),
        temporal_probs=np.asarray(probs),
        temporal_beach_ids=np.asarray(beaches, dtype=object),
        temporal_lags=np.asarray(lags),
        predictions_sink=_sink(labels, probs, beaches),
    )
    diag = metrics["two_tier_diagnostics"]
    assert diag["temporal"]["within_beach_auroc"] == 1.0
    assert diag["temporal"]["n_beaches"] == 2.0
    assert "by_lag" in diag["temporal"]
    assert diag["spatial_beach"]["within_beach_auroc"] == 1.0
    # every backtested candidate is recorded for head-to-head comparison
    assert "xgb_undersample_ensemble" in diag["spatial_beach_by_model"]


def test_stale_within_beach_recorded_separately_from_fresh():
    labels = [0, 1, 0, 1] * 12
    beaches = (["a"] * 2 + ["b"] * 2) * 12
    fresh = [0.1, 0.9, 0.2, 0.8] * 12  # tracks label -> within-beach 1.0
    stale = [0.6, 0.4, 0.55, 0.45] * 12  # inverted -> within-beach 0.0
    sink = {
        ("xgb_undersample_offset", "beach_id"): {
            "labels": np.asarray(labels),
            "probabilities": np.asarray(fresh, dtype=float),
            "probabilities_stale": np.asarray(stale, dtype=float),
            "groups": np.asarray(beaches, dtype=object),
        }
    }
    metrics: dict = {}
    _record_within_beach_diagnostics(
        metrics, winner="xgb_undersample_offset", predictions_sink=sink
    )
    diag = metrics["two_tier_diagnostics"]
    # fresh and served regimes are recorded as distinct numbers
    assert diag["spatial_beach_by_model"]["xgb_undersample_offset"]["within_beach_auroc"] == 1.0
    assert diag["spatial_beach_stale_by_model"]["xgb_undersample_offset"]["within_beach_auroc"] == 0.0
    assert diag["spatial_beach_stale"]["within_beach_auroc"] == 0.0


def test_route_offset_weight_ramp():
    from app.ml.training import _route_offset_weight

    # cutoff 3, blend end 5: fresh→0, day-4 midpoint→0.5, ≥5→1, unknown→1 (offset)
    w = _route_offset_weight(np.array([1.0, 3.0, 4.0, 5.0, 30.0, np.nan]), 3, 5)
    assert list(w) == [0.0, 0.0, 0.5, 1.0, 1.0, 1.0]
    # weight is monotone non-decreasing in age (no band whiplash as a beach ages)
    ages = np.arange(0, 20, dtype=float)
    ramp = _route_offset_weight(ages, 3, 5)
    assert np.all(np.diff(ramp) >= 0)


def test_router_returns_the_blend_weight_it_actually_used():
    """The 5th return is the per-row provenance logged as served_offset_weight.

    model_version records the registry winner (the ensemble) even on rows the
    offset model produced, so this weight is the ONLY thing that attributes a
    served prediction to a model. It must be the same weight used for the blend —
    logging a different array would silently mis-attribute every row.
    """
    from app.ml.training import _route_fresh_stale_probabilities, _route_offset_weight

    class _StubOffset:
        def predict_proba(self, features, beach_ids=None):
            p = np.full(len(features), 0.8)
            return np.column_stack([1.0 - p, p])

    ages = np.array([1.0, 4.0, 30.0])
    features = pd.DataFrame(
        {"days_since_enterococcus_value_obs": ages, "precip_mm_24h": np.zeros(3)}
    )
    metadata = pd.DataFrame({"beach_id": ["a", "b", "c"]})
    ensemble = np.array([0.2, 0.2, 0.2])

    routed, _, _, diag, weights = _route_fresh_stale_probabilities(
        ensemble,
        np.full(3, np.nan),
        np.full(3, np.nan),
        offset_classifier=_StubOffset(),
        offset_calibrator=None,
        features=features,
        metadata=metadata,
    )

    # the returned weight is the ramp, and it is the one that produced `routed`
    assert np.allclose(weights, _route_offset_weight(ages, 3, 5))
    assert np.allclose(routed, (1.0 - weights) * 0.2 + weights * 0.8)
    # fresh row keeps the ensemble, stale row is pure offset, middle is blended
    assert np.isclose(routed[0], 0.2)
    assert np.isclose(routed[2], 0.8)
    assert 0.2 < routed[1] < 0.8
    assert (diag["fresh_beaches"], diag["blended_beaches"], diag["stale_beaches"]) == (1, 1, 1)


def test_temporal_stale_offset_comparison_structure():
    from app.ml.training import _temporal_stale_offset_comparison

    rng = np.random.default_rng(0)
    n = 700
    beach = rng.choice(["a", "b", "c", "d"], size=n)
    y = (rng.random(n) < np.where(np.isin(beach, ["a", "b"]), 0.5, 0.1)).astype(int)
    features = pd.DataFrame(
        {
            "precip_mm_24h": rng.normal(size=n),
            "enterococcus_geomean_30d_lagged": rng.random(n) * 40,
            RECENCY_COLUMN: rng.integers(1, 20, n).astype(float),
        }
    )
    metadata = pd.DataFrame(
        {
            "beach_id": beach,
            "county": np.where(np.isin(beach, ["a", "b"]), "north", "south"),
            "sample_date": pd.date_range("2024-01-01", periods=n, freq="D"),
        }
    )
    idx = np.arange(n)
    out = _temporal_stale_offset_comparison(
        features, y, metadata,
        train_idx=idx[:450], valid_idx=idx[450:550], eval_idx=idx[550:], min_samples=5,
    )
    assert "actual_exceedance_rate" in out
    for model in ("xgb_undersample_ensemble", "xgb_undersample_offset"):
        assert {"fresh", "stale"} <= set(out[model])
        for regime in ("fresh", "stale"):
            block = out[model][regime]
            assert {"within_beach_auroc", "aucpr", "brier", "mean_pred"} <= set(block)
            assert 0.0 <= block["brier"] <= 1.0


def test_persist_writes_beach_id_and_lag(tmp_path):
    n = 24
    beaches = np.array((["a", "b", "c"] * n)[:n], dtype=object)
    features = pd.DataFrame({RECENCY_COLUMN: np.linspace(4, 30, n), "precip_mm_24h": 0.0})
    eval_metadata = pd.DataFrame(
        {"beach_id": beaches, "sample_date": pd.date_range("2026-01-01", periods=n)}
    )
    metrics: dict = {}
    _persist_and_diagnose_holdouts(
        tmp_path,
        winner="xgb_undersample_ensemble",
        metrics=metrics,
        temporal_probs=np.random.default_rng(0).random(n),
        labels=np.random.default_rng(1).integers(0, 2, n),
        eval_idx=np.arange(n),
        eval_metadata=eval_metadata,
        features=features,
        predictions_sink=None,
    )
    written = pd.read_parquet(tmp_path / "holdout_predictions_temporal.parquet")
    assert {"label", "probability", "beach_id", "lag", "date"} <= set(written.columns)
    assert len(written) == n
    assert written["beach_id"].tolist() == list(beaches)
    # lag survived as the real staleness feature, not nulled
    assert written["lag"].notna().all() and written["lag"].min() >= 4
