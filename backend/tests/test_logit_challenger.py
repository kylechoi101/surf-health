import json

import numpy as np
import pandas as pd
import pytest

from app.ml import logit_challenger
from app.ml.calibration import _HIGH_THRESHOLD, _LOW_THRESHOLD
from app.ml.logit_challenger import (
    LOGIT_CHALLENGER_VERSION,
    R_MISSING,
    ChallengerInputs,
    ServingEstimate,
    apply_persistence_floor,
    build_features,
    check_coefficients,
    fit_coefficients,
    lab_history_features,
    precip_station_map,
    predict,
    rain_feature,
)
from app.ml.lookup_serving import LOOKUP_MODEL_VERSION, apply_lookup_to_served, compute_lookup


def _beach_day() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "beach_id": ["a", "a", "a", "b", "b"],
            "sample_date": pd.to_datetime(
                ["2026-01-01", "2026-01-08", "2026-01-15", "2025-12-01", "2026-01-14"]
            ),
            "exceeds_stv": [False, True, False, False, True],
            "enterococcus_action_ratio": [0.1, 10.0, 0.5, 0.2, 2.0],
            "latitude": [33.0, 33.0, 33.0, 34.0, 34.0],
            "longitude": [-118.0, -118.0, -118.0, -119.0, -119.0],
        }
    )


def test_features_are_strictly_prior_and_age_is_in_days():
    """A sample ON the date is ignored, and age is whole days (not seconds)."""
    f = lab_history_features(_beach_day(), ["a", "b"], ["2026-01-15", "2026-01-15"])
    a, b = f.iloc[0], f.iloc[1]
    # Beach a: the 01-15 row is on D, so the last known result is 01-08 (10x the limit).
    assert a["n"] == 2 and a["pos"] == 1
    assert a["age_days"] == 7.0
    assert a["R"] == pytest.approx(1.0)
    assert a["F"] == pytest.approx(np.exp(-2.0))
    assert a["last_exceeds"] == 1.0
    assert b["age_days"] == 1.0
    assert b["F"] == pytest.approx(1.0)


def test_lookup_matches_the_served_compute_lookup():
    bd = _beach_day()
    ours = lab_history_features(bd, ["a", "b", "never"], ["2026-01-20"] * 3).set_index("beach_id")
    served = compute_lookup(bd, "2026-01-20", ["a", "b", "never"]).set_index("beach_id")
    assert np.allclose(ours["lookup"], served["p_lookup"])
    assert (ours["n"] == served["n"]).all()


def test_no_history_in_window_is_neutral():
    f = lab_history_features(_beach_day(), ["never", "a"], ["2026-01-20", "2027-06-01"])
    assert (f["R"] == R_MISSING).all()
    assert (f["F"] == 0.0).all()
    assert f["last_exceeds"].isna().all()


def test_fit_recovers_known_coefficients():
    rng = np.random.default_rng(0)
    n = 40_000
    feats = pd.DataFrame(
        {
            "L": rng.normal(-2.0, 1.0, n),
            "R": rng.normal(-0.8, 0.6, n),
            "RF": rng.normal(-0.2, 0.3, n),
            "W": rng.exponential(0.3, n),
            "S": rng.uniform(-1, 1, n),
        }
    )
    truth = {"intercept": -0.1, "R": 0.4, "RF": 0.7, "W": 0.7, "S": 0.2}
    y = rng.random(n) < predict(feats, truth)
    fitted = fit_coefficients(feats, y)
    for k, v in truth.items():
        assert fitted[k] == pytest.approx(v, abs=0.08)


def test_zero_coefficients_return_the_lookup():
    feats = pd.DataFrame({"L": np.log([0.1 / 0.9, 0.4 / 0.6]), "R": [1.0, -1.0],
                          "RF": [0.5, 0.0], "W": [2.0, 0.0], "S": [1.0, -1.0]})
    zero = {"intercept": 0.0, "R": 0.0, "RF": 0.0, "W": 0.0, "S": 0.0}
    assert np.allclose(predict(feats, zero), [0.1, 0.4])


def test_rain_uses_the_pipelines_pour_point_station_rule():
    precip = pd.DataFrame(
        {
            "station_id": ["near_pour", "near_beach"],
            "latitude": [35.0, 33.0],
            "longitude": [-120.0, -118.0],
            "sample_date": [pd.Timestamp("2026-01-15")] * 2,
            "precip_mm_72h": [25.4 * 0.75, 0.0],
        }
    )
    links = pd.DataFrame(
        {"beach_id": ["a"], "pour_point_latitude": [35.01], "pour_point_longitude": [-120.01]}
    )
    smap = precip_station_map(precip, links, {"a": (33.0, -118.0), "b": (33.0, -118.0)})
    assert smap == {"a": "near_pour", "b": "near_beach"}
    w = rain_feature(precip, smap, ["a", "b", "a"], ["2026-01-15", "2026-01-15", "2026-02-01"])
    # 0.75 in -> log2(1 + 3) = 2; missing date -> dry.
    assert w == pytest.approx([2.0, 0.0, 0.0])


def test_persistence_floor_only_lifts_rows_whose_last_sample_exceeded():
    out = apply_persistence_floor(np.array([0.05, 0.05, 0.5]), np.array([1.0, 0.0, 1.0]))
    assert out == pytest.approx([0.20, 0.05, 0.5])


def test_build_features_combines_terms():
    bd = _beach_day()
    inputs = ChallengerInputs(bd, pd.DataFrame(
        {"station_id": ["s"], "latitude": [33.0], "longitude": [-118.0],
         "sample_date": [pd.Timestamp("2026-01-15")], "precip_mm_72h": [0.0]}
    ), {"a": "s"})
    f = build_features(inputs, ["a"], ["2026-01-15"])
    assert f["RF"].iloc[0] == pytest.approx(f["R"].iloc[0] * f["F"].iloc[0])
    assert f["S"].iloc[0] == pytest.approx(1.0, abs=1e-3)  # Jan 15 is the season peak


def test_missing_ratio_column_refuses_rather_than_reading_every_beach_as_clean():
    with pytest.raises(ValueError, match="enterococcus_action_ratio"):
        lab_history_features(_beach_day().drop(columns="enterococcus_action_ratio"), ["a"], ["2026-01-20"])


def test_an_exceedance_with_no_ratio_reads_at_the_limit_not_as_clean():
    bd = _beach_day()
    bd.loc[(bd["beach_id"] == "b") & (bd["sample_date"] == "2026-01-14"), "enterococcus_action_ratio"] = np.nan
    f = lab_history_features(bd, ["b"], ["2026-01-15"]).iloc[0]
    assert f["last_exceeds"] == 1.0
    assert f["R"] == 0.0


@pytest.mark.parametrize(
    "coefs, rows",
    [
        ({"intercept": 0.0, "R": 0.4, "RF": 0.7, "W": 0.7, "S": np.nan}, 50_000),
        ({"intercept": 0.0, "R": 12.0, "RF": 0.7, "W": 0.7, "S": 0.2}, 50_000),
        ({"intercept": 0.0, "R": 0.4, "RF": 0.7, "W": 0.7, "S": 0.2}, 10),
    ],
)
def test_serving_guards_refuse_a_fit_that_should_not_publish(coefs, rows):
    with pytest.raises(ValueError):
        check_coefficients(coefs, rows, min_train_rows=1_000)


# ---- serving integration (lookup_serving.apply_lookup_to_served) ----

FORECAST_DATE = "2026-01-20"


def _write_curated(tmp_path, with_precip=True, rain_mm=0.0):
    """A small curated dir: weekly samples for 6 beaches over ~2 years, rain-driven labels."""
    rng = np.random.default_rng(7)
    dates = pd.date_range("2024-01-02", "2026-01-13", freq="7D")
    rows = []
    for i, b in enumerate(["a", "b", "c", "d", "e", "f"]):
        for d in dates:
            wet = rng.random() < 0.3
            exceeds = bool(rng.random() < (0.5 if wet else 0.08))
            rows.append({"beach_id": b, "sample_date": d, "exceeds_stv": exceeds,
                         "enterococcus_action_ratio": 3.0 if exceeds else 0.1,
                         "latitude": 33.0 + i, "longitude": -118.0, "_wet": wet})
    bd = pd.DataFrame(rows)
    # Beach "a": last test before D exceeded, so the persistence floor applies.
    bd.loc[(bd["beach_id"] == "a") & (bd["sample_date"] == dates[-1]), ["exceeds_stv", "enterococcus_action_ratio"]] = [True, 2.0]
    bd.drop(columns="_wet").to_parquet(tmp_path / "beach_day.parquet", index=False)
    if with_precip:
        days = pd.date_range("2023-12-01", FORECAST_DATE)
        wet_days = set(bd.loc[bd["_wet"], "sample_date"])
        precip = pd.DataFrame(
            [{"station_id": f"s{i}", "latitude": 33.0 + i, "longitude": -118.0, "sample_date": d,
              "precip_mm_72h": 30.0 if d in wet_days else 0.0}
             for i in range(6) for d in days]
        )
        precip.loc[precip["sample_date"] == pd.Timestamp(FORECAST_DATE), "precip_mm_72h"] = rain_mm
        precip.to_parquet(tmp_path / "precip_daily.parquet", index=False)
    beach_ids = ["a", "b", "c", "d", "e", "f"]
    pd.DataFrame(
        {
            "beach_id": beach_ids,
            "forecast_date": [FORECAST_DATE] * 6,
            "risk_band": ["Low"] * 6,
            "p_exceed": [0.11, 0.12, 0.13, 0.14, 0.15, 0.16],
            "p_exceed_raw": [0.1] * 6,
            "model_version": ["ml-v1"] * 6,
            "forecast_generated_at": ["2026-01-20T08:00:00"] * 6,
            "sample_age_days": [7] * 6,
        }
    ).to_parquet(tmp_path / "forecasts.parquet", index=False)
    pd.DataFrame(
        {"beach_id": ["b"], "status": ["active"], "started_at": [pd.Timestamp("2026-01-18")]}
    ).to_parquet(tmp_path / "advisories.parquet", index=False)
    return beach_ids


@pytest.fixture
def small_fit(monkeypatch):
    monkeypatch.setattr(logit_challenger, "MIN_TRAIN_ROWS", 100)
    monkeypatch.delenv("SHORELIFE_SERVED_ESTIMATE", raising=False)


def test_serving_publishes_the_logistic_estimate_with_product_floors(tmp_path, small_fit):
    _write_curated(tmp_path, rain_mm=40.0)
    summary = apply_lookup_to_served(tmp_path)
    assert summary["serving_method"] == LOGIT_CHALLENGER_VERSION
    assert summary["fallback_reason"] is None

    f = pd.read_parquet(tmp_path / "forecasts.parquet").set_index("beach_id")
    assert (f["model_version"] == LOGIT_CHALLENGER_VERSION).all()
    # The ML's number is kept, the lookup is logged beside the served number.
    assert f["p_exceed_ml"].tolist() == pytest.approx([0.11, 0.12, 0.13, 0.14, 0.15, 0.16])
    lookup = compute_lookup(pd.read_parquet(tmp_path / "beach_day.parquet"), FORECAST_DATE, list(f.index))
    assert f["p_exceed_lookup"].to_numpy() == pytest.approx(lookup["base"].to_numpy())
    # It is a different number from the lookup (rain on D, fresh results).
    assert not np.allclose(f["p_exceed_raw"], f["p_exceed_lookup"])
    # Product rules: last test exceeded -> never Low; posted -> at least High.
    assert f.loc["a", "p_exceed"] >= float(_LOW_THRESHOLD)
    assert f.loc["b", "p_exceed"] >= float(_HIGH_THRESHOLD)
    assert bool(f.loc["b", "advisory_floor_applied"])
    assert ((f["p_exceed_lower"] <= f["p_exceed_raw"] + 1e-12) & (f["p_exceed_raw"] <= f["p_exceed_upper"] + 1e-12)).all()
    # Rain on D was fit as a positive driver and is named in the drivers.
    health = json.loads((tmp_path / "system_health.json").read_text())["serving_method"]
    assert health["name"] == LOGIT_CHALLENGER_VERSION
    assert health["logit"]["coefficients"]["W"] > 0
    assert health["logit"]["rain_coverage"] == 1.0
    # Every beach whose number moved materially says which way, and a named
    # reason never contradicts the direction of the number it explains.
    # Checked against the SERVED number, floors included.
    for bid, row in f.iterrows():
        lines = [d for d in row["top_drivers"] if d.startswith("Today's estimate is")]
        if row["advisory_floor_applied"]:
            assert not lines, (bid, list(row["top_drivers"]))
            continue
        if row["p_exceed"] > row["p_exceed_lookup"] * 1.3:
            assert lines and "above" in lines[0], (bid, list(row["top_drivers"]))
        if row["p_exceed"] < row["p_exceed_lookup"] / 1.3:
            assert lines and "below" in lines[0], (bid, list(row["top_drivers"]))
        if row["p_exceed"] >= row["p_exceed_lookup"]:
            assert not any("below" in line for line in lines), (bid, list(row["top_drivers"]))
        if lines and "below" in lines[0]:
            assert "in of rain" not in lines[0]
    assert any("in of rain in the past 3 days" in d for d in f.loc["c", "top_drivers"])


def test_serving_is_idempotent_and_never_copies_its_own_output_into_p_exceed_ml(tmp_path, small_fit):
    _write_curated(tmp_path)
    apply_lookup_to_served(tmp_path)
    first = pd.read_parquet(tmp_path / "forecasts.parquet")
    apply_lookup_to_served(tmp_path)
    second = pd.read_parquet(tmp_path / "forecasts.parquet")
    assert second["p_exceed_ml"].tolist() == pytest.approx([0.11, 0.12, 0.13, 0.14, 0.15, 0.16])
    assert second["p_exceed"].tolist() == pytest.approx(first["p_exceed"].tolist())
    # A run that falls back after a logistic run must not treat the logistic
    # number as the ML's either.
    apply_lookup_to_served(tmp_path, method="lookup")
    third = pd.read_parquet(tmp_path / "forecasts.parquet")
    assert (third["model_version"] == LOOKUP_MODEL_VERSION).all()
    assert third["p_exceed_ml"].tolist() == pytest.approx([0.11, 0.12, 0.13, 0.14, 0.15, 0.16])


def test_serving_falls_back_to_the_lookup_and_says_why(tmp_path, small_fit):
    _write_curated(tmp_path, with_precip=False)
    summary = apply_lookup_to_served(tmp_path)
    assert summary["serving_method"] == LOOKUP_MODEL_VERSION
    assert "precip_daily" in summary["fallback_reason"]
    f = pd.read_parquet(tmp_path / "forecasts.parquet")
    assert f["p_exceed_raw"].to_numpy() == pytest.approx(f["p_exceed_lookup"].to_numpy())
    health = json.loads((tmp_path / "system_health.json").read_text())["serving_method"]
    assert health["name"] == LOOKUP_MODEL_VERSION and health["method_requested"] == "logit"
    assert "logit" not in health


def test_the_env_switch_serves_the_plain_lookup(tmp_path, small_fit, monkeypatch):
    _write_curated(tmp_path)
    monkeypatch.setenv("SHORELIFE_SERVED_ESTIMATE", "lookup")
    summary = apply_lookup_to_served(tmp_path)
    assert summary["serving_method"] == LOOKUP_MODEL_VERSION
    assert summary["fallback_reason"] is None
    monkeypatch.setenv("SHORELIFE_SERVED_ESTIMATE", "xgboost")
    with pytest.raises(ValueError, match="unknown served-estimate method"):
        apply_lookup_to_served(tmp_path)


def test_a_lookup_term_that_disagrees_with_compute_lookup_is_not_served(tmp_path, small_fit, monkeypatch):
    beach_ids = _write_curated(tmp_path)
    real = logit_challenger.estimate_for_serving

    def skewed(*args, **kwargs):
        est = real(*args, **kwargs)
        frame = est.frame.copy()
        frame["lookup"] = frame["lookup"] + 0.01
        return ServingEstimate(frame, est.coefficients, est.train_rows, est.rain_coverage)

    monkeypatch.setattr(logit_challenger, "estimate_for_serving", skewed)
    summary = apply_lookup_to_served(tmp_path)
    assert summary["serving_method"] == LOOKUP_MODEL_VERSION
    assert "diverged" in summary["fallback_reason"]
    assert len(beach_ids) == summary["rows"]


def test_history_logs_the_lookup_and_keeps_logistic_rows_out_of_p_exceed_ml(tmp_path, small_fit):
    _write_curated(tmp_path)
    history = pd.DataFrame(
        {
            "beach_id": ["a", "a"],
            "forecast_date": [FORECAST_DATE, "2026-01-19"],
            "forecast_generated_at": ["2026-01-20T08:00:00", "2026-01-19T08:00:00"],
            "p_exceed": [0.11, 0.07],
            "p_exceed_raw": [0.11, 0.07],
            "risk_band": ["Low", "Low"],
            # Yesterday was served by the logistic model but its ML copy is missing:
            # it must NOT be backfilled with the served (logistic) number.
            "model_version": ["ml-v1", LOGIT_CHALLENGER_VERSION],
            "persistence_floor_applied": [False, False],
            "served_offset_weight": [np.nan, np.nan],
            "p_exceed_ml": [np.nan, np.nan],
        }
    )
    history.to_parquet(tmp_path / "forecast_history.parquet", index=False)
    apply_lookup_to_served(tmp_path)
    h = pd.read_parquet(tmp_path / "forecast_history.parquet").set_index("forecast_date")
    f = pd.read_parquet(tmp_path / "forecasts.parquet").set_index("beach_id")
    today = h.loc[FORECAST_DATE]
    assert today["model_version"] == LOGIT_CHALLENGER_VERSION
    assert today["p_exceed"] == pytest.approx(f.loc["a", "p_exceed"])
    assert today["p_exceed_lookup"] == pytest.approx(f.loc["a", "p_exceed_lookup"])
    assert today["p_exceed_ml"] == pytest.approx(0.11)
    assert np.isnan(h.loc["2026-01-19", "p_exceed_ml"])


def test_serving_glue_floors_persistence_and_moves_the_interval_with_the_model(tmp_path, small_fit, monkeypatch):
    """Deterministic: a crafted model output, so the floors and interval are pinned exactly."""
    _write_curated(tmp_path)
    # Give "a" a clean record whose LAST test exceeded, so its lookup sits below
    # the persistence floor and both floor paths are actually exercised.
    bd = pd.read_parquet(tmp_path / "beach_day.parquet")
    a = bd["beach_id"] == "a"
    last_a = bd.loc[a, "sample_date"].max()
    bd.loc[a, ["exceeds_stv", "enterococcus_action_ratio"]] = [False, 0.1]
    bd.loc[a & (bd["sample_date"] == last_a), ["exceeds_stv", "enterococcus_action_ratio"]] = [True, 2.0]
    bd.to_parquet(tmp_path / "beach_day.parquet", index=False)
    real = logit_challenger.estimate_for_serving

    def crafted(*args, **kwargs):
        est = real(*args, **kwargs)
        frame = est.frame.copy()
        frame["p_model"] = 0.02  # far below every lookup and below the Low cutoff
        # "a": above its own (tiny) lookup but still under the floor, so the
        # interval shift is upward — the case where shifting the floored bound
        # instead of the raw Beta quantile publishes a different interval.
        frame.loc[frame["beach_id"] == "a", "p_model"] = 0.12
        return ServingEstimate(frame, est.coefficients, est.train_rows, est.rain_coverage)

    monkeypatch.setattr(logit_challenger, "estimate_for_serving", crafted)
    apply_lookup_to_served(tmp_path)
    f = pd.read_parquet(tmp_path / "forecasts.parquet").set_index("beach_id")
    lookup = compute_lookup(pd.read_parquet(tmp_path / "beach_day.parquet"), FORECAST_DATE, list(f.index)).set_index("beach_id")

    # "a" last exceeded: the model says 0.12, the product rule says never Low,
    # and a floored number is never explained as "below its record".
    assert f.loc["a", "p_exceed_raw"] == pytest.approx(float(_LOW_THRESHOLD))
    assert bool(f.loc["a", "persistence_floor_applied"])
    assert lookup.loc["a", "p_lookup"] < float(_LOW_THRESHOLD)
    assert f.loc["a", "p_exceed_lookup"] == pytest.approx(f.loc["a", "p_exceed"])
    assert not any(d.startswith("Today's estimate") for d in f.loc["a", "top_drivers"])
    # "b" is posted: served at the High floor, explained by the advisory alone.
    assert bool(f.loc["b", "advisory_floor_applied"])
    assert not any(d.startswith("Today's estimate") for d in f.loc["b", "top_drivers"])
    # "c" is clean and unposted: served exactly the model, and its interval moved
    # down with it on the logit scale rather than staying the lookup's.
    assert f.loc["c", "p_exceed"] == pytest.approx(0.02)
    assert not bool(f.loc["c", "persistence_floor_applied"])
    assert f.loc["c", "p_exceed_upper"] < lookup.loc["c", "p_exceed_upper"]
    shift = np.log(0.02 / 0.98) - np.log(lookup.loc["c", "p_lookup"] / (1 - lookup.loc["c", "p_lookup"]))
    up = lookup.loc["c", "beta_upper"]
    assert f.loc["c", "p_exceed_upper"] == pytest.approx(1 / (1 + np.exp(-(np.log(up / (1 - up)) + shift))))
    # "a": the interval moves from the raw Beta quantile, not from the 0.20 floor
    # compute_lookup widened its bound to.
    la = lookup.loc["a"]
    shift_a = np.log(0.12 / 0.88) - np.log(la["p_lookup"] / (1 - la["p_lookup"]))
    assert shift_a > 0.5
    lo_a = 1 / (1 + np.exp(-(np.log(la["beta_lower"] / (1 - la["beta_lower"])) + shift_a)))
    assert f.loc["a", "p_exceed_lower"] == pytest.approx(min(lo_a, float(_LOW_THRESHOLD)))
    up_a = 1 / (1 + np.exp(-(np.log(la["beta_upper"] / (1 - la["beta_upper"])) + shift_a)))
    assert f.loc["a", "p_exceed_upper"] == pytest.approx(max(up_a, float(_LOW_THRESHOLD)))


def test_a_dead_rain_feed_serves_the_lookup_instead_of_scoring_everyone_dry(tmp_path, small_fit):
    _write_curated(tmp_path)
    precip = pd.read_parquet(tmp_path / "precip_daily.parquet")
    precip = precip[precip["sample_date"] < pd.Timestamp(FORECAST_DATE)]  # feed stopped at D-1
    precip.to_parquet(tmp_path / "precip_daily.parquet", index=False)
    summary = apply_lookup_to_served(tmp_path)
    assert summary["serving_method"] == LOOKUP_MODEL_VERSION
    assert "rain rows" in summary["fallback_reason"]
