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
                  issued="2026-07-01T18:00:00+00:00", persistence_floor_applied=None):
    row = {
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
    # None == a legacy (pre-2026-08-06) row, which is how pin-era rows are
    # identified; post-change rows always carry a bool.
    if persistence_floor_applied is not None:
        row["persistence_floor_applied"] = persistence_floor_applied
    return row


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


def _pin_era_fixture(tmp_path, *, pinned_realized=0.42, n_pinned=200):
    """600 genuine rows + n_pinned legacy rows recorded at precal == 1.0.

    Mirrors the shipped 2026-08-05 history: the pinned rows realize well below
    1.0, so an isotonic fitted WITH them caps its top step at that realized rate
    and every post-change probability pushed through the map is capped there too.
    """
    rng = np.random.default_rng(3)
    rows, observations = [], []
    day = pd.Timestamp("2026-06-01")
    for i in range(600):
        beach, date = f"g{i}", (day + pd.Timedelta(days=i % 30)).date().isoformat()
        p = 0.02 if i < 450 else 0.75
        exceeded = bool(rng.random() < (0.02 if i < 450 else 0.80))
        rows.append(_forecast_row(beach, date, p=p, issued=f"{date}T18:00:00+00:00"))
        observations.append((beach, date, exceeded))
    for i in range(n_pinned):
        beach, date = f"pin{i}", (day + pd.Timedelta(days=i % 30)).date().isoformat()
        rows.append(_forecast_row(beach, date, p=1.0, issued=f"{date}T18:00:00+00:00"))
        observations.append((beach, date, bool(rng.random() < pinned_realized)))
    _write_forecasts(tmp_path, rows)
    append_forecast_history(tmp_path)
    _write_observations(tmp_path, observations)


def test_fit_excludes_pin_era_rows_so_the_map_is_not_capped(tmp_path):
    # The regression that made this change only half-deployed: pre-2026-08-06 the
    # serve path pinned persistence positives to 1.0 BEFORE p_exceed_precal was
    # captured, so those rows' x-value is a constant rather than a model output.
    # Fitting on them drags the isotonic's top step down to their realized rate
    # and caps EVERY served probability there -- measured on the real history,
    # max(y) = 0.45, which put _VERY_HIGH_THRESHOLD (0.70) out of reach entirely.
    _pin_era_fixture(tmp_path)
    mapping = fit_serving_calibration(tmp_path, min_pairs=100, min_positives=25)
    assert mapping is not None
    assert mapping["n_pin_era_excluded"] == 200
    # Thresholds are set from the WITHOUT-fix value, not from 0.5: leaving the
    # pins in pools them with the genuine high bucket and yields ~0.61, which a
    # `> 0.5` assertion would happily accept. That is exactly how the round-1
    # test failed to differentiate. Measured: 0.611 without the fix, ~0.82 with.
    top = float(apply_serving_calibration(np.array([1.0]), mapping)[0])
    assert top > 0.75, f"pin-era rows still dragging the map's top down to {top:.3f}"
    # The genuine high bucket (served 0.75) realized ~0.80 and must come back at
    # roughly its own rate rather than being averaged down by the pins.
    genuine = float(apply_serving_calibration(np.array([0.75]), mapping)[0])
    assert genuine == pytest.approx(0.80, abs=0.08), genuine


def test_fit_keeps_post_change_rows_even_at_probability_one(tmp_path):
    # NOTE: this is a GUARD, not a regression test -- it passes against the
    # pre-exclusion code too, because back then nothing was dropped at all. It
    # exists to fail if _drop_pin_era_rows is ever widened (e.g. keyed on p_fit
    # alone, or on a date cutoff), which would silently censor real data forever
    # instead of self-limiting. Kept deliberately, labelled deliberately.
    #
    # The exclusion is keyed on "legacy row AND precal == 1.0", so a post-change
    # row carries persistence_floor_applied and survives even at a genuine 1.0.
    _pin_era_fixture(tmp_path, n_pinned=0)
    observations = [(f"g{i}", (pd.Timestamp("2026-06-01") + pd.Timedelta(days=i % 30))
                     .date().isoformat(), bool(i % 5 == 0)) for i in range(600)]
    # 40 POST-change rows at precal 1.0 that genuinely realize — they must survive
    # the exclusion and reach the top of the fitted map.
    extra, day = [], "2026-06-15"
    for i in range(40):
        extra.append(_forecast_row(f"new{i}", day, p=1.0, issued=f"{day}T18:00:00+00:00",
                                   persistence_floor_applied=False))
        observations.append((f"new{i}", day, True))
    _write_forecasts(tmp_path, extra)
    append_forecast_history(tmp_path)
    _write_observations(tmp_path, observations)

    mapping = fit_serving_calibration(tmp_path, min_pairs=100, min_positives=25)
    assert mapping is not None
    assert mapping["n_pin_era_excluded"] == 0, "post-change rows must not be dropped"
    # They all exceeded, and there are enough of them to clear the top-step
    # support floor, so the map must carry them to the top of the scale.
    assert float(apply_serving_calibration(np.array([1.0]), mapping)[0]) > 0.9


def test_fit_caps_a_top_step_too_few_rows_support(tmp_path):
    # PAVA emits y=1.0 off a handful of rows, and this map publishes a public risk
    # number. On the real history the post-exclusion top step was y=1.0 supported
    # by TWO rows -- both Mission Bay stations on one afternoon, i.e. a single
    # spatially-correlated event. Trailing under-supported steps collapse into the
    # highest adequately-supported level instead.
    _pin_era_fixture(tmp_path, n_pinned=0)
    observations = [(f"g{i}", (pd.Timestamp("2026-06-01") + pd.Timedelta(days=i % 30))
                     .date().isoformat(), bool(i % 5 == 0)) for i in range(600)]
    extra, day = [], "2026-06-20"
    for i in range(3):  # below _MIN_TOP_STEP_SUPPORT
        extra.append(_forecast_row(f"thin{i}", day, p=0.99, issued=f"{day}T18:00:00+00:00",
                                   persistence_floor_applied=False))
        observations.append((f"thin{i}", day, True))
    _write_forecasts(tmp_path, extra)
    append_forecast_history(tmp_path)
    _write_observations(tmp_path, observations)

    mapping = fit_serving_calibration(tmp_path, min_pairs=100, min_positives=25)
    assert mapping is not None
    assert mapping["top_step_capped_from"] is not None, "thin top step was not capped"
    assert mapping["y_max"] < 1.0
    assert float(apply_serving_calibration(np.array([1.0]), mapping)[0]) == pytest.approx(
        mapping["y_max"]
    )


def test_apply_passes_nan_and_degenerate_mapping_through():
    mapping = {"x": [0.0, 1.0], "y": [0.0, 0.5]}
    out = apply_serving_calibration(np.array([np.nan, 0.5]), mapping)
    assert np.isnan(out[0])
    assert out[1] == pytest.approx(0.25)
    untouched = apply_serving_calibration(np.array([0.3]), {"x": [0.1], "y": [0.1]})
    assert untouched[0] == pytest.approx(0.3)
