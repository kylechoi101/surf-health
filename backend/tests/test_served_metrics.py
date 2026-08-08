"""Served-forecast accountability loop (app/ml/served_metrics.py)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ml.served_metrics import (
    HISTORY_FILE,
    POOLED_REGIME_CAVEAT,
    annotate_live_regime,
    append_forecast_history,
    apply_serving_calibration,
    daily_outcomes,
    fit_serving_calibration,
    fit_window_composition,
    served_performance,
    serving_calibration_policy,
)
from app.ml.serving_config import ERA_PRE_ROUTER, ERA_ROUTER_LOGGING_GAP_UNKNOWABLE


def _write_forecasts(curated_dir, rows):
    pd.DataFrame(rows).to_parquet(curated_dir / "forecasts.parquet", index=False)


def _forecast_row(beach_id="b1", forecast_date="2026-07-01", p=0.1, band="Low",
                  issued="2026-07-01T18:00:00+00:00", persistence_floor_applied=None,
                  serving_config_fingerprint=None):
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
    if serving_config_fingerprint is not None:
        row["serving_config_fingerprint"] = serving_config_fingerprint
    return row


def _write_observations(curated_dir, rows, *, method=None, units=None):
    frame = pd.DataFrame(rows, columns=["beach_id", "sample_date", "exceeds_stv"])
    if method is not None:
        frame["method"] = method
        frame["units"] = units
    frame.to_parquet(curated_dir / "observations.parquet", index=False)


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
    # Key-INDEPENDENT first: without the cap this fixture yields apply(1.0) == 1.0,
    # so this fails on behaviour rather than on a missing dict key. The payload
    # assertions below would otherwise all differentiate only by KeyError, which
    # is not a regression test -- the exact defect found in the previous round.
    assert float(apply_serving_calibration(np.array([1.0]), mapping)[0]) < 1.0, (
        "under-supported top step was not capped"
    )
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


def test_fit_warns_when_the_ceiling_suppresses_the_very_high_band(tmp_path):
    # The ceiling is whatever the top-supported step happens to be, and it moves
    # as the trailing window rolls. On the shipped history it rests on ~19 rows
    # from a two-week span in early May; when those age out y_max drops toward
    # ~0.49 and Very High becomes unreachable for every beach. Nothing else
    # catches that -- the anomaly gate's band check only fires when non-Low
    # collapses to zero -- so the fit itself has to say so.
    rng = np.random.default_rng(5)
    rows, obs = [], []
    day = pd.Timestamp("2026-06-01")
    for i in range(600):
        beach = f"c{i}"
        d = (day + pd.Timedelta(days=i % 30)).date().isoformat()
        p = float(np.clip(rng.random() * 0.4, 0.01, 0.4))  # nothing scores high
        rows.append(_forecast_row(beach, d, p=p, issued=f"{d}T18:00:00+00:00",
                                  persistence_floor_applied=False))
        obs.append((beach, d, bool(rng.random() < 0.1)))
    _write_forecasts(tmp_path, rows)
    append_forecast_history(tmp_path)
    _write_observations(tmp_path, obs)

    mapping = fit_serving_calibration(tmp_path, min_pairs=100, min_positives=25)
    assert mapping is not None
    assert mapping["y_max"] < 0.70
    assert mapping["ceiling_warning"] is not None
    assert "UNREACHABLE" in mapping["ceiling_warning"]


def test_fit_does_not_warn_when_the_ceiling_clears_every_band(tmp_path):
    _pin_era_fixture(tmp_path, n_pinned=0)
    observations = [(f"g{i}", (pd.Timestamp("2026-06-01") + pd.Timedelta(days=i % 30))
                     .date().isoformat(), bool(i % 5 == 0)) for i in range(600)]
    extra, day = [], "2026-06-15"
    for i in range(40):
        extra.append(_forecast_row(f"hi{i}", day, p=0.98, issued=f"{day}T18:00:00+00:00",
                                   persistence_floor_applied=False))
        observations.append((f"hi{i}", day, True))
    _write_forecasts(tmp_path, extra)
    append_forecast_history(tmp_path)
    _write_observations(tmp_path, observations)

    mapping = fit_serving_calibration(tmp_path, min_pairs=100, min_positives=25)
    assert mapping is not None
    assert mapping["y_max"] >= 0.70
    assert mapping["ceiling_warning"] is None


# ---------------------------------------------------------------------------
# Serving-regime provenance (E5)
# ---------------------------------------------------------------------------


def test_history_gains_the_fingerprint_column_and_old_rows_stay_null(tmp_path):
    """Adding a column to _HISTORY_COLUMNS populates it GOING FORWARD ONLY.

    That is exactly how the 2026-07-22..07-28 hole was created: the router went
    live ~07-22 and `served_offset_weight` only started being written on 07-29,
    so a week of router-served rows is logged as pre-router forever. The right
    behaviour for old rows is therefore a null — a back-filled fingerprint would
    be a fabricated claim about a run nobody observed.
    """
    _write_forecasts(tmp_path, [_forecast_row("old")])
    append_forecast_history(tmp_path)
    _write_forecasts(
        tmp_path,
        [_forecast_row("new", serving_config_fingerprint="0ad71d5001d68746")],
    )
    append_forecast_history(tmp_path)

    history = pd.read_parquet(tmp_path / HISTORY_FILE).set_index("beach_id")
    assert "serving_config_fingerprint" in history.columns
    assert pd.isna(history.loc["old", "serving_config_fingerprint"])
    assert history.loc["new", "serving_config_fingerprint"] == "0ad71d5001d68746"


def test_fit_window_composition_separates_recorded_from_reconstructed():
    pairs = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-07-10", "2026-07-24", "2026-08-08", "2026-08-08"]
            ),
            "served_offset_weight": [None, None, 1.0, 1.0],
            "persistence_floor_applied": [None, None, False, False],
            "serving_config_fingerprint": [None, None, "abc123", "abc123"],
            "model_version": ["a", "a", "b", "c"],
        }
    )
    composition = fit_window_composition(pairs)
    assert composition["n_pairs"] == 4
    assert composition["by_regime"]["abc123"] == 2
    assert composition["by_regime"][f"legacy:{ERA_PRE_ROUTER}"] == 1
    # The unknowable span keeps its own bucket rather than being folded into
    # either neighbour.
    assert composition["by_regime"][f"legacy:{ERA_ROUTER_LOGGING_GAP_UNKNOWABLE}"] == 1
    assert composition["fingerprinted_fraction"] == 0.5
    # model_version is reported but is NOT the regime key: it records the
    # registry winner, which is not what computed p_exceed.
    assert composition["n_distinct_model_versions"] == 3


def test_live_regime_warning_fires_when_the_fit_window_is_all_superseded():
    """The measured 2026-08-07 state: the calibrator applied to today's
    probabilities is fitted on 14,414 pairs, ZERO of them from the running
    configuration."""
    payload = {
        "fit_window_composition": {
            "n_pairs": 14414,
            "by_regime": {f"legacy:{ERA_PRE_ROUTER}": 13425, "older": 989},
        }
    }
    annotate_live_regime(payload, "0ad71d5001d68746")
    composition = payload["fit_window_composition"]
    assert composition["live_fingerprint_pairs"] == 0
    assert composition["live_fingerprint_fraction"] == 0.0
    warning = composition["under_represented_warning"]
    assert warning is not None
    assert "SUPERSEDED" in warning
    # It must NOT be a filter: filtering today leaves 0 pairs and the product
    # would serve uncalibrated probabilities, which run hot.
    assert "Serving it anyway is deliberate" in warning


def test_live_regime_warning_is_silent_when_the_window_is_the_live_regime():
    payload = {
        "fit_window_composition": {
            "n_pairs": 1000,
            "by_regime": {"livefp": 900, f"legacy:{ERA_PRE_ROUTER}": 100},
        }
    }
    annotate_live_regime(payload, "livefp", min_pairs=500)
    assert payload["fit_window_composition"]["under_represented_warning"] is None
    assert payload["fit_window_composition"]["live_fingerprint_fraction"] == 0.9


def test_fit_payload_carries_the_composition(tmp_path):
    _pin_era_fixture(tmp_path, n_pinned=0)
    mapping = fit_serving_calibration(tmp_path, min_pairs=100, min_positives=25)
    assert mapping is not None
    composition = mapping["fit_window_composition"]
    assert composition["n_pairs"] == mapping["n_pairs"]
    assert composition["fingerprinted_fraction"] == 0.0  # fixture rows are legacy
    annotate_live_regime(mapping, "livefp")
    assert mapping["fit_window_composition"]["under_represented_warning"] is not None


def test_serving_calibration_policy_matches_the_module_constants():
    """The fingerprint hashes this policy, so a constant that drifts out of it
    would silently stop being part of the serving regime."""
    from app.ml import served_metrics as module

    policy = serving_calibration_policy()
    assert policy["window_days"] == module._FIT_WINDOW_DAYS
    assert policy["min_pairs"] == module._MIN_FIT_PAIRS
    assert policy["min_positives"] == module._MIN_FIT_POSITIVES
    assert policy["min_top_step_support"] == module._MIN_TOP_STEP_SUPPORT
    assert policy["forward_match_days"] == module.FORWARD_MATCH_DAYS


def _two_regime_history(tmp_path, *, n=120):
    rng = np.random.default_rng(19)
    rows, obs = [], []
    day = pd.Timestamp("2026-06-01")
    for i in range(n):
        beach = f"old{i}"
        d = (day + pd.Timedelta(days=i % 20)).date().isoformat()
        p = float(np.clip(rng.random(), 0.02, 0.9))
        rows.append(_forecast_row(beach, d, p=p, issued=f"{d}T18:00:00+00:00"))
        obs.append((beach, d, bool(rng.random() < p)))
    day2 = pd.Timestamp("2026-07-05")
    for i in range(n):
        beach = f"new{i}"
        d = (day2 + pd.Timedelta(days=i % 20)).date().isoformat()
        p = float(np.clip(rng.random(), 0.02, 0.9))
        rows.append(
            _forecast_row(
                beach, d, p=p, issued=f"{d}T18:00:00+00:00",
                persistence_floor_applied=False,
                serving_config_fingerprint="livefp0000000000",
            )
        )
        obs.append((beach, d, bool(rng.random() < p)))
    _write_forecasts(tmp_path, rows)
    append_forecast_history(tmp_path)
    return obs


def test_served_performance_stratifies_by_regime_and_labels_the_pooled_figure(tmp_path):
    """The published 'how good is the product' number averaged eight models,
    most of them not running. It is kept (consumers read it) but is now labelled
    as pooled and shipped beside its per-regime split."""
    obs = _two_regime_history(tmp_path)
    _write_observations(tmp_path, obs)
    payload = served_performance(tmp_path, windows=(90,))
    window = payload["window_90d"]

    assert window["same_day"]["pooled_across_regimes"] is True
    assert window["same_day"]["pooled_caveat"] == POOLED_REGIME_CAVEAT
    assert "aucpr_caveat" in window["same_day"]

    regimes = window["by_regime"]
    assert "livefp0000000000" in regimes
    assert regimes["livefp0000000000"]["is_reconstructed"] is False
    legacy = [key for key in regimes if key.startswith("legacy:")]
    assert legacy, "pre-fingerprint rows must still be reported, as legacy"
    assert regimes[legacy[0]]["is_reconstructed"] is True
    # Regime and assay stratification compose rather than replace one another.
    assert "by_assay" in regimes["livefp0000000000"]["same_day"]
    assert payload["metric_guidance"]["headline_metric"] == "within_beach_auroc"


def test_assay_stratification_reads_method_and_units_from_observations(tmp_path):
    """Regression. `_matched_from_disk` used to select only
    (beach_id, sample_date, exceeds_stv), so `daily_outcomes` took its
    "no assay columns" branch on every real run and reported the ENTIRE served
    population as culture: the shipped 2026-08-07 payload read
    `pcr: {n_pairs: 0}` against 1,175 ddPCR observations in the same window.
    A stratification that silently collapses to one stratum is worse than none —
    it reads as evidence that the mix is clean.
    """
    rows, obs, methods, units = [], [], [], []
    for i in range(80):
        beach = f"p{i}"
        d = "2026-07-01"
        rows.append(_forecast_row(beach, d, p=0.5, issued=f"{d}T18:00:00+00:00"))
        obs.append((beach, d, bool(i % 2)))
        molecular = i < 40
        methods.append("MCB-ddPCR" if molecular else "Enterolert")
        units.append("Copies/100ml" if molecular else "MPN/100ml")
    _write_forecasts(tmp_path, rows)
    append_forecast_history(tmp_path)
    _write_observations(tmp_path, obs, method=methods, units=units)

    by_assay = served_performance(tmp_path, windows=(90,))["window_90d"]["same_day"]["by_assay"]
    assert by_assay["pcr"]["n_pairs"] == 40, by_assay
    assert by_assay["culture"]["n_pairs"] == 40
    assert by_assay["composition"]["pcr_pair_fraction"] == 0.5
