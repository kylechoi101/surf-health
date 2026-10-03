import json

import numpy as np
import pandas as pd
import pytest

from app.ml import served_metrics
from app.ml.served_metrics import served_performance_for_versions

LOGIT = "logit-lookup-offset-v1"


def _write(tmp_path, n_days=60, beaches=30, seed=0):
    """History served by the ML then the logistic model, with next-day outcomes."""
    rng = np.random.default_rng(seed)
    rows, obs = [], []
    for d in pd.date_range("2026-06-01", periods=n_days):
        version = "ml-v1" if d < pd.Timestamp("2026-06-21") else LOGIT
        for b in range(beaches):
            y = bool(rng.random() < 0.15)
            # the logistic column knows tomorrow a little; the lookup column is flat
            p = float(np.clip(0.1 + (0.4 if y else 0.0) + rng.normal(0, 0.05), 0.01, 0.99))
            rows.append({"beach_id": f"b{b}", "forecast_date": str(d.date()),
                         "forecast_generated_at": f"{d.date()}T08:00:00", "p_exceed": p,
                         "p_exceed_precal": p, "p_exceed_lookup": 0.15,
                         # the ML column is missing on one beach, so the common subset is smaller
                         "p_exceed_ml": np.nan if b == 0 else float(np.clip(p + rng.normal(0, 0.3), 0.01, 0.99)),
                         "model_version": version, "risk_band": "Low"})
            obs.append({"beach_id": f"b{b}", "sample_date": d + pd.Timedelta(days=1), "exceeds_stv": y})
    pd.DataFrame(rows).to_parquet(tmp_path / "forecast_history.parquet", index=False)
    pd.DataFrame(obs).to_parquet(tmp_path / "observations.parquet", index=False)


def test_scores_only_the_requested_version_and_compares_on_the_same_rows(tmp_path):
    _write(tmp_path)
    out = served_performance_for_versions(
        tmp_path, {LOGIT}, compare_columns=("p_exceed_lookup", "p_exceed_ml")
    )
    assert out["first_served"] == "2026-06-21"
    fwd = out["forward_1_3d"]
    # 40 logistic days x 30 beaches, every one with a next-day outcome
    assert fwd["n_pairs"] == 40 * 30
    assert fwd["reportable"] is True
    head = fwd["head_to_head"]
    # every model is scored on the SAME rows: the 29 beaches with an ML value
    assert head["n_pairs"] == 40 * 29
    for name in ("served", "p_exceed_lookup", "p_exceed_ml"):
        assert head[name]["n_pairs"] == head["n_pairs"]
    assert head["served"]["auroc"] > head["p_exceed_ml"]["auroc"] > 0.5
    assert head["p_exceed_lookup"].get("auroc", 0.5) == pytest.approx(0.5)


def test_not_reportable_until_the_calibration_bar(tmp_path, monkeypatch):
    _write(tmp_path, n_days=22, beaches=10)  # 2 logistic days x 10 beaches
    out = served_performance_for_versions(tmp_path, {LOGIT})
    assert out["served_days"] == 2
    assert out["forward_1_3d"]["reportable"] is False


def test_no_rows_for_the_version_is_empty_not_an_error(tmp_path):
    _write(tmp_path, n_days=10)  # all ML
    out = served_performance_for_versions(tmp_path, {LOGIT})
    assert out["served_days"] == 0 and out["first_served"] is None
    assert "forward_1_3d" not in out


def test_live_threshold_matches_the_calibration_guards():
    assert served_metrics.LIVE_MIN_PAIRS == served_metrics._MIN_FIT_PAIRS
    assert served_metrics.LIVE_MIN_POSITIVES == served_metrics._MIN_FIT_POSITIVES


def test_backtest_summary_reads_the_committed_results(tmp_path):
    from app.ml.lookup_serving import _backtest_summary

    curated = tmp_path / "curated"
    exp = tmp_path / "experiments" / "logit_challenger"
    curated.mkdir()
    exp.mkdir(parents=True)
    assert _backtest_summary(curated) is None
    exp.joinpath("results.json").write_text(json.dumps({
        "window": ["2025-09-01", "2026-09-21"],
        "outcomes": {"forward_1_3d": {"all": {
            "n": 10, "base_rate": 0.1,
            "challenger": {"auroc": 0.85, "aucpr": 0.59, "brier": 0.077, "within_beach_auroc": 0.64},
            "lookup": {"auroc": 0.83, "aucpr": 0.55, "brier": 0.080, "within_beach_auroc": 0.45},
        }}},
    }))
    out = _backtest_summary(curated)
    assert out["logit"]["auroc"] == 0.85 and out["lookup"]["within_beach_auroc"] == 0.45
    assert out["same_rows"] is None  # this fixture has no served-log overlap slice


def test_backtest_same_rows_carries_the_ml_that_served():
    from pathlib import Path

    from app.ml.lookup_serving import _backtest_summary

    curated = Path(__file__).resolve().parents[2] / "data" / "curated"
    same = _backtest_summary(curated)["same_rows"]
    assert same["n"] > 10_000
    # the like-for-like ML number the site must show instead of the sample-day 0.79
    assert 0.2 < same["ml"]["aucpr"] < 0.5
    assert same["logit"]["aucpr"] > same["ml"]["aucpr"]


def test_the_committed_backtest_is_where_serving_looks_for_it():
    from pathlib import Path

    from app.ml.lookup_serving import _BACKTEST_RESULTS, _backtest_summary

    curated = Path(__file__).resolve().parents[2] / "data" / "curated"
    assert (curated / _BACKTEST_RESULTS).exists()
    assert _backtest_summary(curated)["n"] > 10_000


def test_score_carries_within_beach_auroc_over_beaches_with_both_outcomes():
    pairs = pd.DataFrame({
        "beach_id": ["a"] * 4 + ["b"] * 4 + ["c"] * 3,
        # a and b each rank their own positive above their negatives; c never exceeds
        "p_exceed": [0.9, 0.1, 0.2, 0.3, 0.8, 0.2, 0.1, 0.3, 0.95, 0.96, 0.97],
        "outcome_forward": [1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0],
    })
    scored = served_metrics._score(pairs, "outcome_forward")
    assert scored["within_beach_auroc"] == pytest.approx(1.0)
    # the pooled AUROC is not the same number — c's high-p negatives drag it down
    assert scored["auroc"] < 1.0


def test_head_to_head_entries_carry_a_seeded_beach_cluster_ci(tmp_path):
    _write(tmp_path)
    cols = ("p_exceed_lookup", "p_exceed_ml")
    first = served_performance_for_versions(tmp_path, {LOGIT}, compare_columns=cols)
    again = served_performance_for_versions(tmp_path, {LOGIT}, compare_columns=cols)
    head = first["forward_1_3d"]["head_to_head"]
    assert "ci" not in head["served"]
    for name in cols:
        ci = head[name]["ci"]
        assert set(ci) == {"within_beach_auroc", "auroc", "brier"}
        for low, high in ci.values():
            assert low is None or high is None or low <= high
    # the served column beats the flat lookup, so (lookup - served) AUROC is negative
    assert head["p_exceed_lookup"]["ci"]["auroc"][1] < 0
    assert again["forward_1_3d"]["head_to_head"] == head  # fixed seed


def test_not_reportable_under_28_served_days_even_with_enough_pairs(tmp_path):
    _write(tmp_path, n_days=20 + 27, beaches=60)  # 27 logistic days x 60 beaches
    out = served_performance_for_versions(tmp_path, {LOGIT}, compare_columns=("p_exceed_lookup",))
    fwd = out["forward_1_3d"]
    assert out["served_days"] == 27
    assert fwd["n_pairs"] >= served_metrics.LIVE_MIN_PAIRS
    assert fwd["n_positive"] >= served_metrics.LIVE_MIN_POSITIVES
    assert fwd["reportable"] is False
    assert fwd["head_to_head"]["reportable"] is False

    _write(tmp_path, n_days=20 + 28, beaches=60)
    out = served_performance_for_versions(tmp_path, {LOGIT}, compare_columns=("p_exceed_lookup",))
    assert out["served_days"] == 28
    assert out["forward_1_3d"]["reportable"] is True
    assert out["forward_1_3d"]["head_to_head"]["reportable"] is True
