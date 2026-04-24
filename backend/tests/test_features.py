import math

import pandas as pd

from app.data.pipeline.features import (
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
