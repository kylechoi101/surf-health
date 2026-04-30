import math

import pandas as pd

from app.data.pipeline.features import build_inference_features
from app.data.pipeline.stormwater import (
    add_rain_policy_features,
    build_beach_stormwater_features,
    normalize_stormwater_assets,
)


def test_normalize_stormwater_assets_accepts_arcgis_points_and_low_flow_metadata():
    raw = pd.DataFrame(
        [
            {
                "FACILITYID": "OC-1",
                "GlobalID": "{abc}",
                "LOW_FLOW_DIVERSION": "Yes",
                "INSPECTED": "Verified",
                "geometry": {"x": -117.93, "y": 33.61},
            },
            {
                "NAME": "Pico Kenter",
                "asset_type": "discharge_point",
                "low_flow_diversion": "no",
                "latitude": "34.010",
                "longitude": "-118.500",
            },
        ]
    )

    assets = normalize_stormwater_assets(raw, source_name="unit_source", default_city="Santa Monica")

    assert list(assets["asset_id"]) == ["OC-1", "Pico Kenter"]
    assert list(assets["asset_type"]) == ["outfall", "discharge_point"]
    assert list(assets["low_flow_diversion_flag"]) == [1, 0]
    assert list(assets["field_verified_flag"]) == [1, 0]
    assert assets.loc[0, "latitude"] == 33.61
    assert assets.loc[1, "longitude"] == -118.5


def test_build_beach_stormwater_features_counts_nearby_assets_and_ceden_tmdl_rows():
    beaches = pd.DataFrame(
        [
            {"beach_id": "near", "latitude": 33.6000, "longitude": -117.9000},
            {"beach_id": "far", "latitude": 35.0000, "longitude": -120.0000},
        ]
    )
    assets = pd.DataFrame(
        [
            {
                "asset_id": "a",
                "asset_type": "outfall",
                "source_name": "oc_outfalls",
                "latitude": 33.6010,
                "longitude": -117.9010,
                "low_flow_diversion_flag": 1,
                "field_verified_flag": 1,
                "tmdl_bacteria_flag": 0,
                "impaired_water_flag": 0,
            },
            {
                "asset_id": "b",
                "asset_type": "tmdl_receiving_water",
                "source_name": "ceden_tmdl",
                "latitude": 33.6050,
                "longitude": -117.9050,
                "low_flow_diversion_flag": 0,
                "field_verified_flag": 0,
                "tmdl_bacteria_flag": 1,
                "impaired_water_flag": 1,
            },
        ]
    )

    features = build_beach_stormwater_features(beaches, assets)

    near = features.set_index("beach_id").loc["near"]
    assert near["stormwater_asset_count_1km"] == 2
    assert near["stormwater_tmdl_site_count_2km"] == 1
    assert near["stormwater_low_flow_diversion_count_2km"] == 1
    assert near["stormwater_impaired_water_count_2km"] == 1
    assert near["nearest_stormwater_asset_km"] < 0.2
    assert math.isnan(features.set_index("beach_id").loc["far"]["nearest_stormwater_asset_km"])


def test_add_rain_policy_features_encodes_expert_thresholds_without_overwriting_precip():
    frame = pd.DataFrame(
        [
            {"beach_id": "a", "sample_date": "2026-01-01", "precip_mm_72h": 2.53},
            {"beach_id": "a", "sample_date": "2026-01-02", "precip_mm_72h": 2.54},
            {"beach_id": "a", "sample_date": "2026-01-03", "precip_mm_72h": 5.08},
        ]
    )

    result = add_rain_policy_features(frame)

    assert list(result["rain_72h_monitoring_pause_flag"]) == [0, 1, 1]
    assert list(result["rain_72h_general_advisory_flag"]) == [0, 0, 1]
    assert list(result["rain_72h_inches"]) == [2.53 / 25.4, 0.1, 0.2]
    assert "precip_mm_72h" in result.columns


def test_stormwater_columns_survive_feature_selection_for_training():
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
                "nearest_stormwater_asset_km": 0.2,
                "stormwater_asset_count_1km": 2,
                "rain_72h_general_advisory_flag": 1,
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
                "nearest_stormwater_asset_km": 0.2,
                "stormwater_asset_count_1km": 2,
                "rain_72h_general_advisory_flag": 1,
            },
        ]
    )

    dataset = build_inference_features(frame)

    assert dataset.feature_frame.iloc[0]["nearest_stormwater_asset_km"] == 0.2
    assert dataset.feature_frame.iloc[0]["stormwater_asset_count_1km"] == 2
    assert dataset.feature_frame.iloc[0]["rain_72h_general_advisory_flag"] == 1
