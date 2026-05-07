import math

import numpy as np
import pandas as pd

from app.data.pipeline.features import (
    REGULATORY_GEOMEAN_COLUMNS,
    _regulatory_geomean_features,
    add_temporal_features,
    build_inference_features,
    build_inference_windows,
    build_sliding_windows,
)


def test_build_sliding_windows_emits_lagged_dataset():
    frame = pd.DataFrame(
        [
            {
                "beach_id": "alpha",
                "county": "San Diego",
                "region": "San Diego",
                "sample_date": f"2026-04-{day:02d}",
                "sample_time": f"2026-04-{day:02d}T08:00:00-07:00",
                "enterococcus_value": 20 + day,
                "exceeds_stv": int(day > 7),
                "latitude": 32.9,
                "longitude": -117.3,
                "historical_advisory_count": 10,
                "cdip_distance_km": 7.5,
                "erddap_distance_km": 4.2,
                "cdip_station_id": "191",
                "erddap_source_name": "cencoos_del_mar_mooring",
                "wave_height_m": 1.0 + day * 0.1,
                "dominant_period_s": 10.0,
                "wave_direction_deg": 225.0,
                "water_temperature_c": 14.0,
                "salinity_psu": 33.0,
                "uv_index": 5.0,
                "wind_speed_mps": 4.0,
            }
            for day in range(1, 11)
        ]
    )
    dataset = build_sliding_windows(frame)
    assert len(dataset.feature_frame) > 0
    assert dataset.sequence_array.shape[1] == 30
    assert "sin_doy" in dataset.feature_frame.columns
    assert "log_enterococcus" not in dataset.feature_frame.columns
    assert "wave_height_m" not in dataset.feature_frame.columns
    assert "wave_direction_deg" not in dataset.feature_frame.columns
    assert "latitude" not in dataset.feature_frame.columns
    assert "county" not in dataset.feature_frame.columns


def test_build_sliding_windows_uses_antecedent_history_only():
    frame = pd.DataFrame(
        [
            {
                "beach_id": "alpha",
                "sample_date": f"2026-04-{day:02d}",
                "sample_time": f"2026-04-{day:02d}T08:00:00-07:00",
                "enterococcus_value": 20 + day,
                "exceeds_stv": int(day > 7),
                "wave_height_m": 1.0 + day * 0.1,
                "dominant_period_s": 10.0,
                "wave_direction_deg": 210.0,
                "water_temperature_c": 14.0,
                "salinity_psu": 33.0,
                "uv_index": 5.0,
                "wind_speed_mps": 4.0,
            }
            for day in range(1, 6)
        ]
    )

    dataset = build_sliding_windows(frame)

    assert len(dataset.feature_frame) == 2
    assert dataset.feature_frame.iloc[0]["enterococcus_value_lag_1"] == 23
    assert dataset.sequence_array[0, -1, 0] == 23
    assert math.isclose(dataset.feature_frame.iloc[0]["wave_height_m_mean_7d"], 1.2)
    assert dataset.feature_frame.iloc[0]["days_since_wave_height_m_obs"] == 1.0
    assert dataset.targets_log_density[0] == math.log10(24)


def test_build_inference_windows_emits_only_unlabeled_forecast_rows():
    observed = [
        {
            "beach_id": "alpha",
            "sample_date": f"2026-04-{day:02d}",
            "sample_time": f"2026-04-{day:02d}T08:00:00-07:00",
            "enterococcus_value": 20 + day,
            "exceeds_stv": int(day > 7),
            "wave_height_m": 1.0 + day * 0.1,
            "dominant_period_s": 10.0,
            "wave_direction_deg": 200.0,
            "water_temperature_c": 14.0,
            "salinity_psu": 33.0,
            "uv_index": 5.0,
            "wind_speed_mps": 4.0,
        }
        for day in range(1, 5)
    ]
    forecast_candidate = {
        "beach_id": "alpha",
        "sample_date": "2026-04-05",
        "sample_time": "2026-04-05T05:00:00-07:00",
        "enterococcus_value": None,
        "exceeds_stv": None,
        "wave_height_m": 1.6,
        "dominant_period_s": 10.0,
        "wave_direction_deg": 205.0,
        "water_temperature_c": 14.0,
        "salinity_psu": 33.0,
        "uv_index": 6.0,
        "wind_speed_mps": 4.0,
    }

    dataset = build_inference_windows(pd.DataFrame(observed + [forecast_candidate]))

    assert len(dataset.feature_frame) == 1
    assert str(dataset.metadata.iloc[0]["sample_date"].date()) == "2026-04-05"
    assert dataset.feature_frame.iloc[0]["enterococcus_value_lag_1"] == 24
    assert dataset.sequence_array[0, -1, 0] == 24


def test_build_inference_features_keeps_unlabeled_rows_without_sequence_history():
    frame = pd.DataFrame(
        [
            {
                "beach_id": "alpha",
                "sample_date": "2026-04-01",
                "sample_time": "2026-04-01T08:00:00-07:00",
                "enterococcus_value": 21.0,
                "exceeds_stv": 0,
                "wave_height_m": 1.0,
                "dominant_period_s": 10.0,
                "wave_direction_deg": 215.0,
                "water_temperature_c": 14.0,
                "salinity_psu": 33.0,
                "uv_index": 5.0,
                "wind_speed_mps": 4.0,
            },
            {
                "beach_id": "alpha",
                "sample_date": "2026-04-02",
                "sample_time": "2026-04-02T05:00:00-07:00",
                "enterococcus_value": None,
                "exceeds_stv": None,
                "wave_height_m": 1.1,
                "dominant_period_s": 10.0,
                "wave_direction_deg": 220.0,
                "water_temperature_c": 14.0,
                "salinity_psu": 33.0,
                "uv_index": 6.0,
                "wind_speed_mps": 4.0,
            },
        ]
    )

    dataset = build_inference_features(frame)

    assert len(dataset.feature_frame) == 1
    assert str(dataset.metadata.iloc[0]["sample_date"].date()) == "2026-04-02"
    assert "wave_height_m" not in dataset.feature_frame.columns
    assert dataset.feature_frame.iloc[0]["wave_height_m_lag_1"] == 1.0


def test_build_inference_features_adds_constrained_hydrology_lag_kernel():
    frame = pd.DataFrame(
        [
            {
                "beach_id": "alpha",
                "sample_date": "2026-04-01",
                "sample_time": "2026-04-01T08:00:00-07:00",
                "enterococcus_value": 21.0,
                "exceeds_stv": 0,
                "wave_height_m": 1.0,
                "dominant_period_s": 10.0,
                "water_temperature_c": 14.0,
                "salinity_psu": 33.0,
                "uv_index": 5.0,
                "wind_speed_mps": 4.0,
                "precip_mm_6h": 2.0,
                "precip_mm_24h": 5.0,
                "precip_mm_48h": 8.0,
                "precip_mm_72h": 13.0,
                "precip_mm_7d": 21.0,
                "streamflow_cfs_latest": 10.0,
                "streamflow_cfs_mean_24h": 6.0,
                "streamflow_cfs_max_24h": 14.0,
            },
            {
                "beach_id": "alpha",
                "sample_date": "2026-04-02",
                "sample_time": "2026-04-02T05:00:00-07:00",
                "enterococcus_value": None,
                "exceeds_stv": None,
                "wave_height_m": 1.1,
                "dominant_period_s": 10.0,
                "water_temperature_c": 14.0,
                "salinity_psu": 33.0,
                "uv_index": 6.0,
                "wind_speed_mps": 4.0,
                "precip_mm_6h": 0.0,
                "precip_mm_24h": 1.0,
                "precip_mm_48h": 2.0,
                "precip_mm_72h": 3.0,
                "precip_mm_7d": 4.0,
                "streamflow_cfs_latest": 8.0,
                "streamflow_cfs_mean_24h": 7.0,
                "streamflow_cfs_max_24h": 9.0,
            },
        ]
    )

    dataset = build_inference_features(frame)

    assert "precip_runoff_lag_kernel_7d" in dataset.feature_frame.columns
    assert dataset.feature_frame.iloc[0]["precip_runoff_lag_kernel_7d"] >= 0.0
    assert dataset.feature_frame.iloc[0]["streamflow_lag_kernel_24h"] >= 0.0


def test_build_sliding_windows_uses_calendar_day_lags_for_sparse_history():
    frame = pd.DataFrame(
        [
            {
                "beach_id": "alpha",
                "sample_date": "2026-04-01",
                "sample_time": "2026-04-01T08:00:00-07:00",
                "enterococcus_value": 21.0,
                "exceeds_stv": 0,
                "wave_height_m": 1.0,
                "dominant_period_s": 10.0,
                "wave_direction_deg": 190.0,
                "water_temperature_c": 14.0,
                "salinity_psu": 33.0,
                "uv_index": 5.0,
                "wind_speed_mps": 4.0,
            },
            {
                "beach_id": "alpha",
                "sample_date": "2026-04-03",
                "sample_time": "2026-04-03T08:00:00-07:00",
                "enterococcus_value": 23.0,
                "exceeds_stv": 0,
                "wave_height_m": 1.2,
                "dominant_period_s": 10.0,
                "wave_direction_deg": 195.0,
                "water_temperature_c": 14.0,
                "salinity_psu": 33.0,
                "uv_index": 5.0,
                "wind_speed_mps": 4.0,
            },
            {
                "beach_id": "alpha",
                "sample_date": "2026-04-04",
                "sample_time": "2026-04-04T08:00:00-07:00",
                "enterococcus_value": 24.0,
                "exceeds_stv": 0,
                "wave_height_m": 1.3,
                "dominant_period_s": 10.0,
                "wave_direction_deg": 200.0,
                "water_temperature_c": 14.0,
                "salinity_psu": 33.0,
                "uv_index": 5.0,
                "wind_speed_mps": 4.0,
            },
            {
                "beach_id": "alpha",
                "sample_date": "2026-04-10",
                "sample_time": "2026-04-10T08:00:00-07:00",
                "enterococcus_value": 30.0,
                "exceeds_stv": 0,
                "wave_height_m": 1.8,
                "dominant_period_s": 10.0,
                "wave_direction_deg": 205.0,
                "water_temperature_c": 14.0,
                "salinity_psu": 33.0,
                "uv_index": 5.0,
                "wind_speed_mps": 4.0,
            },
        ]
    )

    dataset = build_sliding_windows(frame)

    assert len(dataset.feature_frame) == 1
    assert pd.isna(dataset.feature_frame.iloc[0]["enterococcus_value_lag_1"])
    assert dataset.feature_frame.iloc[0]["enterococcus_value_lag_7"] == 23.0
    assert dataset.feature_frame.iloc[0]["days_since_previous_sample"] == 6.0
    assert dataset.sequence_array[0, -6, 0] == 24.0
    assert dataset.sequence_array[0, -7, 0] == 23.0
    assert dataset.sequence_array[0, -9, 0] == 21.0


def _make_history(beach_id: str, start: str, values: list[float]) -> pd.DataFrame:
    base_date = pd.Timestamp(start)
    rows = []
    for offset, value in enumerate(values):
        sample_date = base_date + pd.Timedelta(days=offset)
        rows.append(
            {
                "beach_id": beach_id,
                "sample_date": sample_date.strftime("%Y-%m-%d"),
                "sample_time": sample_date.strftime("%Y-%m-%dT08:00:00-07:00"),
                "enterococcus_value": value,
                "exceeds_stv": int(value >= 104),
                "wave_height_m": 1.0,
                "dominant_period_s": 10.0,
                "wave_direction_deg": 200.0,
                "water_temperature_c": 14.0,
                "salinity_psu": 33.0,
                "uv_index": 5.0,
                "wind_speed_mps": 4.0,
            }
        )
    return pd.DataFrame(rows)


def test_regulatory_geomean_features_match_log10_arithmetic_mean():
    """Geomean of n samples == 10 ** mean(log10(samples)). The window must include
    only *prior* samples — the same-day sample on row k is never in the rolling
    window for row k.
    """
    history_values = [10.0, 100.0, 50.0, 200.0, 35.0, 1000.0, 80.0]
    frame = _make_history("alpha", "2026-04-01", history_values)
    enriched = add_temporal_features(frame)
    geomean = _regulatory_geomean_features(enriched)

    # Row 0: no prior samples -> NaN until min_periods reached. Min_periods=2,
    # so row 0 is NaN, row 1 is NaN, row 2 has 2 prior samples.
    assert pd.isna(geomean.iloc[0]["enterococcus_geomean_30d_lagged"])
    assert pd.isna(geomean.iloc[1]["enterococcus_geomean_30d_lagged"])

    # Row 2: prior samples are values[:2] = [10, 100], geomean = sqrt(10*100) = ~31.62.
    expected_geomean_row2 = 10 ** ((math.log10(10) + math.log10(100)) / 2)
    assert math.isclose(
        float(geomean.iloc[2]["enterococcus_geomean_30d_lagged"]),
        expected_geomean_row2,
        rel_tol=1e-9,
    )

    # Row 6: prior samples are values[:6] = [10, 100, 50, 200, 35, 1000], geomean
    # = 10 ** mean(log10) = 10 ** 1.957 ≈ 90.6.
    log_mean_row6 = np.mean([math.log10(v) for v in history_values[:6]])
    expected_geomean_row6 = 10 ** log_mean_row6
    assert math.isclose(
        float(geomean.iloc[6]["enterococcus_geomean_30d_lagged"]),
        expected_geomean_row6,
        rel_tol=1e-9,
    )

    # Threshold flags: 10 ** 1.957 = ~90.6 -> exceeds 35 (yes) but not 104 (no).
    assert geomean.iloc[6]["geomean_30d_exceeds_35_lagged"] == 1.0
    assert geomean.iloc[6]["geomean_30d_exceeds_104_lagged"] == 0.0


def test_regulatory_geomean_does_not_leak_same_day_sample():
    """If the same-day sample 1000 entered the window for row k, the geomean
    would be much higher and trip exceeds_104. The closed='left' contract
    guarantees this never happens.
    """
    values = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 1000.0]
    frame = _make_history("alpha", "2026-04-01", values)
    enriched = add_temporal_features(frame)
    geomean = _regulatory_geomean_features(enriched)

    last_row_geomean = float(geomean.iloc[-1]["enterococcus_geomean_30d_lagged"])
    # Window for last row should contain only the six 10.0 samples; geomean = 10.
    assert math.isclose(last_row_geomean, 10.0, rel_tol=1e-9)
    assert geomean.iloc[-1]["geomean_30d_exceeds_104_lagged"] == 0.0
    assert geomean.iloc[-1]["geomean_30d_exceeds_35_lagged"] == 0.0


def test_regulatory_geomean_columns_appear_in_sliding_window_dataset():
    """The new geomean columns must reach the model's feature frame, otherwise
    the training step will silently ignore them.
    """
    # Need >= ~30 rows so build_sliding_windows has enough history.
    values = [25.0 + 10.0 * (i % 3) for i in range(40)]
    frame = _make_history("alpha", "2026-04-01", values)
    dataset = build_sliding_windows(frame)
    feature_columns = set(dataset.feature_frame.columns)
    for column in REGULATORY_GEOMEAN_COLUMNS:
        assert column in feature_columns, f"{column} missing from sliding-window feature frame"
