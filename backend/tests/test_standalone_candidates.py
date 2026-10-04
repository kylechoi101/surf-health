"""build_candidates must serve the same beach set as training's forecast export."""

from datetime import date

import numpy as np
import pandas as pd

from app.ml.lookup_serving import build_candidates
from app.ml.training import (
    ENTEROCOCCUS_RATIO_COLUMN,
    _build_forecast_candidates,
    _load_curated_training_frame,
)

FORECAST = date(2026, 10, 2)


def _rows(beach_id, days_ago, *, status="supported", value=10.0, hour=9):
    return [
        {
            "beach_id": beach_id,
            "sample_date": pd.Timestamp(FORECAST) - pd.Timedelta(days=d),
            "sample_time": pd.Timestamp(FORECAST) - pd.Timedelta(days=d) + pd.Timedelta(hours=hour),
            "enterococcus_value": value,
            ENTEROCOCCUS_RATIO_COLUMN: value / 104.0,
            "exceeds_stv": 0,
            "support_status": status,
            "county": "X",
        }
        for d in days_ago
    ]


def _fixture(tmp_path):
    rows = []
    rows += _rows("served", [3, 10, 17, 24])
    rows += _rows("served_29d", [29, 36, 43])  # newest sample exactly at the cutoff edge
    rows += _rows("stale_31d", [31, 38, 45])  # newest sample older than 30d
    rows += _rows("two_rows", [3, 10])  # fewer than 3 history rows
    rows += _rows("unsupported", [3, 10, 17], status="unsupported")
    rows += _rows("on_forecast_day", [0, 10, 17, 24])  # the row on D is not history, but 3 prior rows remain
    rows += _rows("only_on_d_and_one", [0, 5])
    rows += _rows("outside_window", [1200, 1210, 1220, 1230])  # beyond 1095d of newest sample
    rows += _rows("future_row", [-1, 4, 11, 18])  # row after D is not history
    rows += _rows("nan_value", [3, 10, 17], value=np.nan)
    pd.DataFrame(rows).to_parquet(tmp_path / "beach_day.parquet", index=False)


def _training_beach_ids(tmp_path, window_days=1095, recency=30):
    full = _load_curated_training_frame(tmp_path)
    full["sample_date"] = pd.to_datetime(full["sample_date"])
    frame = full.loc[full["sample_date"] > (full["sample_date"].max() - pd.Timedelta(days=window_days))]
    stations = pd.DataFrame({"beach_id": sorted(set(full["beach_id"]))})
    _, candidates = _build_forecast_candidates(
        frame,
        stations,
        pd.DataFrame(),
        FORECAST,
        full_frame=full,
        min_sample_recency_days=recency,
    )
    return candidates


def test_build_candidates_serves_the_beach_set_training_exports(tmp_path):
    _fixture(tmp_path)
    expected = _training_beach_ids(tmp_path)
    got = build_candidates(tmp_path, FORECAST)

    assert list(got["beach_id"]) == list(expected["beach_id"])  # set AND order
    assert set(got["beach_id"]) == {"served", "served_29d", "future_row", "on_forecast_day"}
    assert list(got["sample_age_days"]) == list(expected["sample_age_days"])
    assert list(got["sample_recency_band"]) == list(expected["sample_recency_band"])
    assert list(got["latest_sample_date"]) == list(expected["latest_sample_date"])


def test_build_candidates_without_recency_cutoff_matches_training(tmp_path):
    _fixture(tmp_path)
    expected = _training_beach_ids(tmp_path, recency=None)
    got = build_candidates(tmp_path, FORECAST, min_recency_days=None)
    assert list(got["beach_id"]) == list(expected["beach_id"])
    assert "stale_31d" in set(got["beach_id"])


def test_build_candidates_window_matches_training(tmp_path):
    _fixture(tmp_path)
    expected = _training_beach_ids(tmp_path, window_days=20, recency=None)
    got = build_candidates(tmp_path, FORECAST, training_window_days=20, min_recency_days=None)
    assert list(got["beach_id"]) == list(expected["beach_id"])


def test_build_candidates_carries_the_fixed_columns(tmp_path):
    _fixture(tmp_path)
    got = build_candidates(tmp_path, FORECAST).set_index("beach_id")
    assert got.loc["served", "forecast_date"] == "2026-10-02"
    assert got.loc["served", "sample_age_days"] == 3
    assert got.loc["served", "sample_recency_band"] == "fresh"
    assert got.loc["served_29d", "sample_recency_band"] == "stale"
    assert bool(got.loc["served", "is_beta_forecast"]) is True
    assert got.loc["served", "forecast_label_mode"] == "model"


def _env_fixture(tmp_path):
    rows = []
    for beach, waves, salinity in (
        ("with_env", [np.nan, 2.0, 5.0, 3.0], [30.0, 31.0, 32.0, 33.0]),
        ("window_nan", [np.nan] * 4, [np.nan] * 4),  # no reading anywhere -> null
        ("old_only", [np.nan, np.nan, np.nan, np.nan], [np.nan] * 4),
    ):
        for i, d in enumerate([3, 10, 17, 24]):
            rows += [
                {
                    **r,
                    "wave_height_m": waves[i],
                    "salinity_psu": salinity[i],
                    "dominant_period_s": 9.0,
                    "uv_index": 4.0,
                    "exceeds_stv": 0,
                }
                for r in _rows(beach, [d])
            ]
    # An old reading outside the 20-day window; the full history still has it.
    rows += [{**r, "wave_height_m": 7.5} for r in _rows("old_only", [900])]
    pd.DataFrame(rows).to_parquet(tmp_path / "beach_day.parquet", index=False)
    pd.DataFrame(
        {"beach_id": ["with_env", "window_nan", "old_only"], "zip_code": ["90001", "90002", None]}
    ).to_parquet(tmp_path / "beaches.parquet", index=False)
    pd.DataFrame(
        {
            "zip_code": ["90001"],
            "forecast_date": [pd.Timestamp(FORECAST)],
            "uv_index": [9.0],
            "uv_alert": ["High"],
        }
    ).to_parquet(tmp_path / "uv_daily.parquet", index=False)


def test_build_candidates_env_columns_match_training(tmp_path):
    _env_fixture(tmp_path)
    full = _load_curated_training_frame(tmp_path)
    full["sample_date"] = pd.to_datetime(full["sample_date"])
    frame = full.loc[full["sample_date"] > (full["sample_date"].max() - pd.Timedelta(days=20))]
    stations = pd.read_parquet(tmp_path / "beaches.parquet")
    uv = pd.read_parquet(tmp_path / "uv_daily.parquet")
    _, expected = _build_forecast_candidates(
        frame, stations, uv, FORECAST, full_frame=full, min_sample_recency_days=30
    )
    expected = expected.set_index("beach_id")
    got = build_candidates(tmp_path, FORECAST, training_window_days=20).set_index("beach_id")

    assert list(got.index) == list(expected.index)
    for column in ("wave_height_m", "dominant_period_s", "water_temperature_c", "salinity_psu", "wind_speed_mps"):
        for beach in got.index:
            want = expected.loc[beach, column]
            have = got.loc[beach, column]
            assert (pd.isna(want) and pd.isna(have)) or want == have, (beach, column, want, have)
    # newest non-null in the window, not simply the newest row
    assert got.loc["with_env", "wave_height_m"] == 2.0
    # window has nothing -> falls back to the full history (training's env-persistence)
    assert got.loc["old_only", "wave_height_m"] == 7.5
    # uv from uv_daily by the beach's zip beats the beach_day value; no zip match keeps it
    assert got.loc["with_env", "uv_index"] == 9.0
    assert got.loc["with_env", "uv_alert"] == "High"
    assert got.loc["window_nan", "uv_index"] == 4.0
    assert pd.isna(got.loc["window_nan", "uv_alert"])


def test_standalone_out_never_writes_into_curated(tmp_path):
    from app.ml.lookup_serving import serve_standalone

    curated = tmp_path / "curated"
    out = tmp_path / "out"
    curated.mkdir()
    _env_fixture(curated)
    (curated / "system_health.json").write_text("{}")

    def snapshot():
        return {p.name: p.read_bytes() for p in sorted(curated.iterdir())}

    before = snapshot()
    summary = serve_standalone(curated, out, FORECAST, method="lookup")

    assert snapshot() == before  # not a byte, not a new file
    assert not (curated / "forecasts.parquet").exists()
    served = pd.read_parquet(out / "forecasts.parquet")
    assert len(served) == summary["rows"] == 3
    assert set(served["model_version"]) == {"lookup-365d-v1"}
    assert served["p_exceed_ml"].isna().all() and served["p_exceed_precal"].isna().all()
    assert "latest_sample_date" not in served.columns
    assert "serving_method" in (out / "system_health.json").read_text()


def test_standalone_logs_todays_forecast_to_history(tmp_path):
    """Without training nothing else appends today's rows; standalone serving must."""
    from app.ml.lookup_serving import apply_lookup_to_served, serve_standalone

    curated = tmp_path / "curated"
    curated.mkdir()
    _env_fixture(curated)
    (curated / "system_health.json").write_text("{}")
    earlier = pd.DataFrame(
        {
            "beach_id": ["with_env"],
            "forecast_date": ["2026-10-01"],
            "forecast_generated_at": ["2026-10-01T20:00:00+00:00"],
            "p_exceed": [0.1],
            "model_version": ["logit-lookup-offset-v1"],
        }
    )
    earlier.to_parquet(curated / "forecast_history.parquet", index=False)

    summary = serve_standalone(curated, None, FORECAST, method="lookup")

    served = pd.read_parquet(curated / "forecasts.parquet")
    history = pd.read_parquet(curated / "forecast_history.parquet")
    assert summary["history_appended"] == len(served) == 3
    today = history[history["forecast_date"].astype(str) == str(FORECAST)]
    assert sorted(today["beach_id"]) == sorted(served["beach_id"])
    merged = today.merge(served[["beach_id", "p_exceed"]], on="beach_id", suffixes=("", "_served"))
    assert np.allclose(merged["p_exceed"], merged["p_exceed_served"])
    assert len(history) == len(earlier) + 3  # the earlier row is kept

    # The workflow re-applies the estimate after advisory expiry: it updates
    # today's rows in place and must not log them a second time.
    apply_lookup_to_served(curated, method="lookup")
    assert len(pd.read_parquet(curated / "forecast_history.parquet")) == len(earlier) + 3
