import pandas as pd
import pytest

from app.ml.lookup_serving import compute_lookup


def test_compute_lookup_strictly_prior_row_on_d_ignored():
    """(1) strictly prior — a row ON D is ignored."""
    forecast_date = "2026-09-22"

    beach_day = pd.DataFrame(
        {
            "beach_id": [
                "beach_prior_only",
                "beach_with_same_day",
                "beach_with_same_day",
                "beach_future",
            ],
            "sample_date": [
                pd.Timestamp("2026-09-20"),
                pd.Timestamp("2026-09-21"),
                pd.Timestamp("2026-09-22"),  # ON D — must be ignored
                pd.Timestamp("2026-09-23"),  # AFTER D — must be ignored
            ],
            "exceeds_stv": [False, False, True, True],
        }
    )

    df = compute_lookup(
        beach_day=beach_day,
        forecast_date=forecast_date,
        beach_ids=["beach_prior_only", "beach_with_same_day", "beach_future"],
    )

    records = df.set_index("beach_id").to_dict("index")

    # Overall pooled mean over rows strictly in [D-365d, D):
    # Only 2 valid rows: 2026-09-20 (False) and 2026-09-21 (False).
    # g = 0.0
    assert df["g"].iloc[0] == pytest.approx(0.0)

    # beach_with_same_day has 1 valid row (2026-09-21, False); row on 2026-09-22 ignored
    b_same = records["beach_with_same_day"]
    assert b_same["n"] == 1
    assert b_same["pos"] == 0
    assert b_same["p_lookup"] == pytest.approx(0.0)
    assert pd.to_datetime(b_same["last_sample_date"]) == pd.Timestamp("2026-09-21")
    assert b_same["last_exceeds"] is False

    # beach_prior_only has 1 valid row (2026-09-20, False)
    b_prior = records["beach_prior_only"]
    assert b_prior["n"] == 1
    assert b_prior["pos"] == 0
    assert b_prior["p_lookup"] == pytest.approx(0.0)
    assert pd.to_datetime(b_prior["last_sample_date"]) == pd.Timestamp("2026-09-20")
    assert b_prior["last_exceeds"] is False

    # beach_future has 0 rows strictly prior to D
    b_future = records["beach_future"]
    assert b_future["n"] == 0
    assert b_future["pos"] == 0
    assert b_future["p_lookup"] == pytest.approx(0.0)
    assert pd.isna(b_future["last_sample_date"])
    assert pd.isna(b_future["last_exceeds"])


def test_compute_lookup_zero_sample_beach_gets_exactly_g():
    """(2) n=0 beach gets exactly g."""
    forecast_date = "2026-09-22"

    beach_day = pd.DataFrame(
        {
            "beach_id": ["beach_active"] * 10
            + ["beach_ancient"],  # ancient row outside 365d window
            "sample_date": [
                pd.Timestamp("2026-05-01") + pd.Timedelta(days=i * 5) for i in range(10)
            ]
            + [pd.Timestamp("2024-01-01")],
            "exceeds_stv": [True, True, True, False, False, False, False, False, False, False]
            + [True],
        }
    )

    # In window [2025-09-22, 2026-09-22): 10 rows for beach_active, 3 exceeds -> g = 0.3
    df = compute_lookup(
        beach_day=beach_day,
        forecast_date=forecast_date,
        beach_ids=["beach_active", "beach_unseen", "beach_ancient"],
    )

    records = df.set_index("beach_id").to_dict("index")
    g = 3.0 / 10.0
    assert df["g"].iloc[0] == pytest.approx(g)

    # Active beach
    b_act = records["beach_active"]
    assert b_act["n"] == 10
    assert b_act["pos"] == 3
    # p_lookup = (3 + 5*0.3)/(10 + 5) = 4.5 / 15 = 0.3
    assert b_act["p_lookup"] == pytest.approx(g)
    assert pd.notna(b_act["last_sample_date"])
    assert b_act["last_exceeds"] is False

    # Unseen beach (never in beach_day)
    b_unseen = records["beach_unseen"]
    assert b_unseen["n"] == 0
    assert b_unseen["pos"] == 0
    assert b_unseen["p_lookup"] == pytest.approx(g)
    assert pd.isna(b_unseen["last_sample_date"])
    assert pd.isna(b_unseen["last_exceeds"])
    assert b_unseen["base"] == pytest.approx(g)
    assert b_unseen["persistence_floor_applied"] is False

    # Ancient beach (no rows within trailing 365 days)
    b_anc = records["beach_ancient"]
    assert b_anc["n"] == 0
    assert b_anc["pos"] == 0
    assert b_anc["p_lookup"] == pytest.approx(g)
    assert pd.isna(b_anc["last_sample_date"])
    assert pd.isna(b_anc["last_exceeds"])
    assert b_anc["base"] == pytest.approx(g)
    assert b_anc["persistence_floor_applied"] is False


def test_persistence_floor_binds_and_sets_flag():
    """(3) persistence floor binds and sets the flag."""
    forecast_date = "2026-09-22"
    from app.ml.calibration import _LOW_THRESHOLD

    # Beach with low empirical rate but recent exceedance:
    # 20 samples, 1 exceedance on the most recent day (2026-09-21).
    beach_day = pd.DataFrame(
        {
            "beach_id": ["b_persist"] * 20 + ["b_clean"] * 20,
            "sample_date": [
                pd.Timestamp("2026-01-01") + pd.Timedelta(days=i * 10) for i in range(19)
            ]
            + [pd.Timestamp("2026-09-21")]
            + [pd.Timestamp("2026-01-01") + pd.Timedelta(days=i * 10) for i in range(20)],
            "exceeds_stv": [False] * 19 + [True] + [False] * 20,
        }
    )

    df = compute_lookup(
        beach_day=beach_day,
        forecast_date=forecast_date,
        beach_ids=["b_persist", "b_clean"],
    )
    records = df.set_index("beach_id").to_dict("index")

    b_p = records["b_persist"]
    assert b_p["last_exceeds"] is True
    assert b_p["p_lookup"] < float(_LOW_THRESHOLD)
    assert b_p["persistence_floor_applied"] is True
    assert b_p["base"] == pytest.approx(float(_LOW_THRESHOLD))

    b_c = records["b_clean"]
    assert b_c["last_exceeds"] is False
    assert b_c["persistence_floor_applied"] is False
    assert b_c["base"] == pytest.approx(b_c["p_lookup"])


def test_posted_beach_floored_to_high_threshold_with_raw_unfloored(tmp_path):
    """(4) posted beach floored to `_HIGH_THRESHOLD` with `p_exceed_raw` unfloored."""
    from app.ml.calibration import _HIGH_THRESHOLD
    from app.ml.lookup_serving import apply_lookup_to_served

    forecast_date = "2026-09-22"
    forecasts = pd.DataFrame(
        {
            "beach_id": ["b_posted", "b_unposted"],
            "forecast_date": [forecast_date, forecast_date],
            "risk_band": ["Low", "Low"],
            "p_exceed": [0.05, 0.05],
            "p_exceed_raw": [0.05, 0.05],
            "p_exceed_precal": [0.05, 0.05],
            "model_version": ["ml-v1", "ml-v1"],
            "forecast_generated_at": ["2026-09-22T08:00:00", "2026-09-22T08:00:00"],
            "sample_age_days": [2, 2],
            "sample_recency_band": ["recent", "recent"],
            "forecast_label_mode": ["model", "model"],
        }
    )
    forecasts.to_parquet(tmp_path / "forecasts.parquet", index=False)

    # Clean beach_day (0 exceeds -> base will be low < 0.30)
    beach_day = pd.DataFrame(
        {
            "beach_id": ["b_posted"] * 10 + ["b_unposted"] * 10,
            "sample_date": [
                pd.Timestamp("2026-08-01") + pd.Timedelta(days=i) for i in range(10)
            ]
            * 2,
            "exceeds_stv": [False] * 20,
        }
    )
    beach_day.to_parquet(tmp_path / "beach_day.parquet", index=False)

    # Active advisory for b_posted
    advisories = pd.DataFrame(
        {
            "beach_id": ["b_posted"],
            "status": ["active"],
            "started_at": [pd.Timestamp("2026-09-20")],
        }
    )
    advisories.to_parquet(tmp_path / "advisories.parquet", index=False)

    summary = apply_lookup_to_served(tmp_path)
    assert summary["posted"] == 1
    assert summary["advisory_floored"] == 1

    res = pd.read_parquet(tmp_path / "forecasts.parquet").set_index("beach_id").to_dict("index")

    b_post = res["b_posted"]
    assert b_post["p_exceed_raw"] < float(_HIGH_THRESHOLD)
    assert b_post["p_exceed"] == pytest.approx(float(_HIGH_THRESHOLD))
    assert b_post["advisory_floor_applied"] is True
    assert b_post["risk_band"] == "High"

    b_unpost = res["b_unposted"]
    assert b_unpost["p_exceed_raw"] < float(_HIGH_THRESHOLD)
    assert b_unpost["p_exceed"] == pytest.approx(b_unpost["p_exceed_raw"])
    assert b_unpost["advisory_floor_applied"] is False
    assert b_unpost["risk_band"] == "Low"


def test_credible_interval_bounds_p_exceed_raw():
    """(5) lower <= p_exceed_raw <= upper."""
    forecast_date = "2026-09-22"
    beach_day = pd.DataFrame(
        {
            "beach_id": ["b_low"] * 10
            + ["b_high"] * 10
            + ["b_persist"] * 10
            + ["b_few"] * 2,
            "sample_date": [
                pd.Timestamp("2026-08-01") + pd.Timedelta(days=i) for i in range(10)
            ]
            * 3
            + [pd.Timestamp("2026-08-01"), pd.Timestamp("2026-08-02")],
            "exceeds_stv": [False] * 10
            + [True] * 10
            + ([False] * 9 + [True])
            + [False, True],
        }
    )

    df = compute_lookup(
        beach_day=beach_day,
        forecast_date=forecast_date,
        beach_ids=["b_low", "b_high", "b_persist", "b_few", "b_zero"],
    )

    assert (df["p_exceed_lower"] <= df["p_exceed_raw"] + 1e-9).all()
    assert (df["p_exceed_raw"] <= df["p_exceed_upper"] + 1e-9).all()


def test_idempotency_preserves_p_exceed_ml(tmp_path):
    """(6) idempotency — running `apply_lookup_to_served` twice leaves `p_exceed_ml` equal to the original ML value."""
    from app.ml.lookup_serving import LOOKUP_MODEL_VERSION, apply_lookup_to_served

    forecast_date = "2026-09-22"
    orig_p = [0.123, 0.456, 0.789]
    forecasts = pd.DataFrame(
        {
            "beach_id": ["b1", "b2", "b3"],
            "forecast_date": [forecast_date] * 3,
            "risk_band": ["Low", "High", "Very High"],
            "p_exceed": orig_p,
            "p_exceed_raw": orig_p,
            "p_exceed_precal": orig_p,
            "model_version": ["ml-v2"] * 3,
            "forecast_generated_at": ["2026-09-22T08:00:00"] * 3,
            "sample_age_days": [1, 2, 3],
            "sample_recency_band": ["fresh", "recent", "recent"],
            "forecast_label_mode": ["model"] * 3,
        }
    )
    forecasts.to_parquet(tmp_path / "forecasts.parquet", index=False)

    # First run
    apply_lookup_to_served(tmp_path)
    f1 = pd.read_parquet(tmp_path / "forecasts.parquet")
    assert (f1["model_version"] == LOOKUP_MODEL_VERSION).all()
    assert f1["p_exceed_ml"].tolist() == pytest.approx(orig_p)
    assert f1["risk_band_ml"].tolist() == ["Low", "High", "Very High"]

    # Second run
    apply_lookup_to_served(tmp_path)
    f2 = pd.read_parquet(tmp_path / "forecasts.parquet")
    assert (f2["model_version"] == LOOKUP_MODEL_VERSION).all()
    assert f2["p_exceed_ml"].tolist() == pytest.approx(orig_p)
    assert f2["risk_band_ml"].tolist() == ["Low", "High", "Very High"]


def test_history_rows_for_today_updated_older_rows_backfilled(tmp_path):
    """(7) history rows for today updated, older rows backfilled."""
    from app.ml.lookup_serving import LOOKUP_MODEL_VERSION, apply_lookup_to_served

    today = "2026-09-22"
    gen_today = "2026-09-22T08:00:00"
    forecasts = pd.DataFrame(
        {
            "beach_id": ["b1"],
            "forecast_date": [today],
            "risk_band": ["High"],
            "p_exceed": [0.65],
            "p_exceed_raw": [0.65],
            "p_exceed_precal": [0.60],
            "model_version": ["ml-v1"],
            "forecast_generated_at": [gen_today],
            "sample_age_days": [2],
            "sample_recency_band": ["recent"],
            "forecast_label_mode": ["model"],
        }
    )
    forecasts.to_parquet(tmp_path / "forecasts.parquet", index=False)

    history = pd.DataFrame(
        {
            "beach_id": ["b1", "b1"],
            "forecast_date": [today, "2026-09-20"],
            "forecast_generated_at": [gen_today, "2026-09-20T08:00:00"],
            "p_exceed": [0.65, 0.25],
            "p_exceed_raw": [0.65, 0.25],
            "p_exceed_precal": [0.60, 0.22],
            "risk_band": ["High", "Moderate"],
            "model_version": ["ml-v1", "ml-v0"],
            "persistence_floor_applied": [False, False],
            "served_offset_weight": [1.0, 1.0],
            "sample_age_days": [2, 4],
        }
    )
    history.to_parquet(tmp_path / "forecast_history.parquet", index=False)

    apply_lookup_to_served(tmp_path)

    hist_after = pd.read_parquet(tmp_path / "forecast_history.parquet")
    assert "p_exceed_ml" in hist_after.columns

    today_row = hist_after[hist_after["forecast_date"] == today].iloc[0]
    assert today_row["model_version"] == LOOKUP_MODEL_VERSION
    assert today_row["p_exceed_ml"] == pytest.approx(0.65)  # Preserved original ML value
    assert pd.isna(today_row["served_offset_weight"])

    older_row = hist_after[hist_after["forecast_date"] == "2026-09-20"].iloc[0]
    assert older_row["model_version"] == "ml-v0"
    assert older_row["p_exceed_ml"] == pytest.approx(0.25)  # Backfilled from p_exceed
    assert older_row["p_exceed"] == pytest.approx(0.25)


def test_history_columns_contains_p_exceed_ml():
    """(8) `_HISTORY_COLUMNS` contains `p_exceed_ml`."""
    from app.ml.served_metrics import _HISTORY_COLUMNS, _PROBABILITY_COLUMNS

    assert "p_exceed_ml" in _HISTORY_COLUMNS
    assert "p_exceed_ml" in _PROBABILITY_COLUMNS
