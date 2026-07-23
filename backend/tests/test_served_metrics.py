"""Served-forecast accountability loop (app/ml/served_metrics.py)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ml.served_metrics import (
    HISTORY_FILE,
    append_forecast_history,
    apply_serving_calibration,
    daily_outcomes,
    fit_serving_calibration,
    served_performance,
)


def _write_forecasts(curated_dir, rows):
    pd.DataFrame(rows).to_parquet(curated_dir / "forecasts.parquet", index=False)


def _forecast_row(beach_id="b1", forecast_date="2026-07-01", p=0.1, band="Low",
                  issued="2026-07-01T18:00:00+00:00"):
    return {
        "beach_id": beach_id,
        "forecast_date": forecast_date,
        "p_exceed": p,
        "p_exceed_raw": p,
        "p_exceed_precal": p,
        "risk_band": band,
        "sample_age_days": 9,
        "model_version": "test-v0",
        "forecast_generated_at": issued,
    }


def _write_observations(curated_dir, rows):
    pd.DataFrame(
        rows, columns=["beach_id", "sample_date", "exceeds_stv"]
    ).to_parquet(curated_dir / "observations.parquet", index=False)


def test_daily_outcomes_worst_sample_wins():
    observations = pd.DataFrame(
        {
            "beach_id": ["b1", "b1", "b2"],
            "sample_date": ["2026-07-01", "2026-07-01", "2026-07-01"],
            "exceeds_stv": [False, True, False],
        }
    )
    outcomes = daily_outcomes(observations)
    assert len(outcomes) == 2
    assert int(outcomes.loc[outcomes["beach_id"] == "b1", "exceeded"].iloc[0]) == 1
    assert int(outcomes.loc[outcomes["beach_id"] == "b2", "exceeded"].iloc[0]) == 0


def test_append_is_idempotent(tmp_path):
    _write_forecasts(tmp_path, [_forecast_row()])
    assert append_forecast_history(tmp_path) == 1
    assert append_forecast_history(tmp_path) == 0
    history = pd.read_parquet(tmp_path / HISTORY_FILE)
    assert len(history) == 1
    # A re-issue (new generated_at) appends a distinct row.
    _write_forecasts(tmp_path, [_forecast_row(issued="2026-07-01T20:00:00+00:00", p=0.3)])
    assert append_forecast_history(tmp_path) == 1
    assert len(pd.read_parquet(tmp_path / HISTORY_FILE)) == 2


def test_append_tolerates_missing_precal_column(tmp_path):
    row = _forecast_row()
    row.pop("p_exceed_precal")
    _write_forecasts(tmp_path, [row])
    append_forecast_history(tmp_path)
    history = pd.read_parquet(tmp_path / HISTORY_FILE)
    assert "p_exceed_precal" in history.columns
    assert np.isnan(history["p_exceed_precal"].iloc[0])


def test_served_performance_same_day_forward_and_banding(tmp_path):
    # Beach b1: forecast on 07-01 (two issues — the later one counts), sampled
    # same day, exceeded. Beach b2: forecast 07-01, first sample 07-02 (clean).
    # Beach b3: forecast 07-01, no sample within 3 days -> unmatched.
    _write_forecasts(
        tmp_path,
        [
            _forecast_row("b1", p=0.9, band="High", issued="2026-07-01T12:00:00+00:00"),
            _forecast_row("b1", p=0.8, band="High", issued="2026-07-01T18:00:00+00:00"),
            _forecast_row("b2", p=0.05, band="Low"),
            _forecast_row("b3", p=0.5, band="High"),
        ],
    )
    append_forecast_history(tmp_path)
    _write_observations(
        tmp_path,
        [
            ("b1", "2026-07-01", True),
            ("b2", "2026-07-02", False),
            ("b4", "2026-07-10", False),  # keeps max outcome date recent
        ],
    )
    payload = served_performance(tmp_path)
    same_day = payload["window_90d"]["same_day"]
    assert same_day["n_pairs"] == 1
    assert same_day["n_positive"] == 1
    band = same_day["band_operating"]
    assert band["exceedances"] == 1
    assert band["sensitivity"] == 1.0
    assert band["exceedances_shown_low"] == 0
    forward = payload["window_90d"]["forward_1_3d"]
    assert forward["n_pairs"] == 1  # b2 matched at D+1; b3 never matched
    assert forward["n_positive"] == 0
    # b1, b2, b3 are all old enough to be checkable; 2 of 3 got an outcome.
    assert payload["verifiable_fraction"] == pytest.approx(2 / 3, abs=1e-4)


def test_fit_returns_none_below_minimums(tmp_path):
    _write_forecasts(tmp_path, [_forecast_row()])
    append_forecast_history(tmp_path)
    _write_observations(tmp_path, [("b1", "2026-07-01", True)])
    assert fit_serving_calibration(tmp_path) is None


def test_fit_and_apply_shrink_overconfident_tail(tmp_path):
    # 600 pairs: 500 served at 0.02 (2% real rate), 100 served at 0.98 but only
    # ~35% real — the audit's exact overconfidence shape.
    rng = np.random.default_rng(7)
    rows, observations = [], []
    day = pd.Timestamp("2026-06-01")
    for i in range(600):
        beach = f"b{i}"
        date = (day + pd.Timedelta(days=i % 30)).date().isoformat()
        p = 0.02 if i < 500 else 0.98
        exceeded = bool(rng.random() < (0.02 if i < 500 else 0.35))
        rows.append(_forecast_row(beach, date, p=p, issued=f"{date}T18:00:00+00:00"))
        observations.append((beach, date, exceeded))
    _write_forecasts(tmp_path, rows)
    append_forecast_history(tmp_path)
    _write_observations(tmp_path, observations)
    mapping = fit_serving_calibration(tmp_path, min_pairs=500, min_positives=25)
    assert mapping is not None
    assert mapping["brier_after"] <= mapping["brier_before"]
    calibrated = apply_serving_calibration(np.array([0.02, 0.98]), mapping)
    assert calibrated[0] < 0.1
    assert 0.15 < calibrated[1] < 0.6  # ~0.35, definitely not ~0.98
    assert calibrated[0] < calibrated[1]  # monotone: rank preserved


def test_apply_passes_nan_and_degenerate_mapping_through():
    mapping = {"x": [0.0, 1.0], "y": [0.0, 0.5]}
    out = apply_serving_calibration(np.array([np.nan, 0.5]), mapping)
    assert np.isnan(out[0])
    assert out[1] == pytest.approx(0.25)
    untouched = apply_serving_calibration(np.array([0.3]), {"x": [0.1], "y": [0.1]})
    assert untouched[0] == pytest.approx(0.3)
