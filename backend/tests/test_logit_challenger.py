import numpy as np
import pandas as pd
import pytest

from app.ml.logit_challenger import (
    R_MISSING,
    ChallengerInputs,
    apply_persistence_floor,
    build_features,
    fit_coefficients,
    lab_history_features,
    precip_station_map,
    predict,
    rain_feature,
    score_forecast_date,
)
from app.ml.lookup_serving import compute_lookup


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


def test_shadow_scoring_writes_its_own_file_and_leaves_serving_untouched(tmp_path):
    rng = np.random.default_rng(1)
    dates = pd.date_range("2025-01-01", "2026-01-14", freq="7D")
    rows = []
    for b, lat in (("a", 33.0), ("b", 34.0)):
        for d in dates:
            exceeds = bool(rng.random() < 0.2)
            rows.append({"beach_id": b, "sample_date": d, "exceeds_stv": exceeds,
                         "enterococcus_action_ratio": 3.0 if exceeds else 0.1,
                         "latitude": lat, "longitude": -118.0})
    pd.DataFrame(rows).to_parquet(tmp_path / "beach_day.parquet")
    pd.DataFrame(
        {"station_id": "s", "latitude": 33.5, "longitude": -118.0,
         "sample_date": pd.date_range("2024-12-01", "2026-01-20"), "precip_mm_72h": 0.0}
    ).to_parquet(tmp_path / "precip_daily.parquet")
    forecasts = pd.DataFrame({"beach_id": ["a", "b"], "forecast_date": ["2026-01-20"] * 2,
                              "p_exceed": [0.1, 0.2]})
    forecasts.to_parquet(tmp_path / "forecasts.parquet")

    summary = score_forecast_date(tmp_path)

    assert summary["rows"] == 2 and summary["train_rows"] > 50
    out = pd.read_parquet(tmp_path / "challenger_forecasts.parquet")
    assert list(out["beach_id"]) == ["a", "b"]
    assert out["p_exceed_challenger"].between(0, 1).all()
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "forecasts.parquet"), forecasts)
