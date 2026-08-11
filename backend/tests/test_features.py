import math

import numpy as np
import pandas as pd

from app.data.pipeline.features import (
    CULTURE_ENTEROCOCCUS_STV,
    REGULATORY_GEOMEAN_COLUMNS,
    SD_BOUNDARY_FLAG_COLUMNS,
    SD_BOUNDARY_INTERACTION_COLUMNS,
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
    # Bacteria-history features are on the action-value ratio scale. This frame
    # carries no method/units, so add_temporal_features divides by the culture
    # action value (see ENTEROCOCCUS_RATIO_COLUMN).
    assert dataset.feature_frame.iloc[0][
        "enterococcus_action_ratio_lag_1"
    ] == 23 / CULTURE_ENTEROCOCCUS_STV
    assert dataset.sequence_array[0, -1, 0] == 23 / CULTURE_ENTEROCOCCUS_STV
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
    assert dataset.feature_frame.iloc[0][
        "enterococcus_action_ratio_lag_1"
    ] == 24 / CULTURE_ENTEROCOCCUS_STV
    assert dataset.sequence_array[0, -1, 0] == 24 / CULTURE_ENTEROCOCCUS_STV


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
    assert pd.isna(dataset.feature_frame.iloc[0]["enterococcus_action_ratio_lag_1"])
    assert dataset.feature_frame.iloc[0][
        "enterococcus_action_ratio_lag_7"
    ] == 23.0 / CULTURE_ENTEROCOCCUS_STV
    assert dataset.feature_frame.iloc[0]["days_since_previous_sample"] == 6.0
    assert dataset.sequence_array[0, -6, 0] == np.float32(24.0 / CULTURE_ENTEROCOCCUS_STV)
    assert dataset.sequence_array[0, -7, 0] == np.float32(23.0 / CULTURE_ENTEROCOCCUS_STV)
    assert dataset.sequence_array[0, -9, 0] == np.float32(21.0 / CULTURE_ENTEROCOCCUS_STV)


def test_exact_lag_features_survive_a_non_contiguous_index():
    """Regression: a ``.loc[mask]`` filter leaves a non-contiguous index, while
    ``_exact_lag_features`` builds its block with ``.merge()`` and so returns a fresh
    RangeIndex.  ``add_temporal_features`` combines the two with ``pd.concat(axis=1)``,
    which aligns on index — so the two UNION instead of aligning and every ``*_lag_*``
    value lands on the wrong row.  Production hit both training entry points:
    ``enterococcus_action_ratio_lag_7`` was correct on only 33% of rows and the lag block
    retained 55% of its signal.  The lag frame must carry the caller's index.
    """

    def _row(beach_id: str, date: str, value: float) -> dict:
        return {
            "beach_id": beach_id,
            "sample_date": date,
            "sample_time": f"{date}T08:00:00-07:00",
            "enterococcus_value": value,
            "exceeds_stv": 0,
            "wave_height_m": 1.5,
            "dominant_period_s": 10.0,
            "wave_direction_deg": 200.0,
            "water_temperature_c": 15.0,
            "salinity_psu": 33.0,
            "uv_index": 5.0,
            "wind_speed_mps": 4.0,
        }

    # Same history as test_build_sliding_windows_uses_calendar_day_lags_for_sparse_history
    # (2026-04-10 minus 7d -> the 04-03 sample, 23.0), but with a second beach
    # interleaved so filtering it out punches holes in the index — exactly what the
    # training-window cut in training.py produces.
    frame = pd.DataFrame(
        [
            _row("filler", "2026-04-01", 99.0),
            _row("alpha", "2026-04-01", 21.0),
            _row("filler", "2026-04-02", 99.0),
            _row("alpha", "2026-04-03", 23.0),
            _row("filler", "2026-04-03", 99.0),
            _row("alpha", "2026-04-04", 24.0),
            _row("filler", "2026-04-09", 99.0),
            _row("alpha", "2026-04-10", 30.0),
        ]
    )
    filtered = frame.loc[frame["beach_id"] == "alpha"]
    assert not filtered.index.equals(pd.RangeIndex(len(filtered))), "precondition"

    dataset = build_sliding_windows(filtered)

    assert len(dataset.feature_frame) == 1
    assert dataset.feature_frame.iloc[0][
        "enterococcus_action_ratio_lag_7"
    ] == 23.0 / CULTURE_ENTEROCOCCUS_STV


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
    assert pd.isna(geomean.iloc[0]["enterococcus_action_ratio_geomean_30d_lagged"])
    assert pd.isna(geomean.iloc[1]["enterococcus_action_ratio_geomean_30d_lagged"])

    # Row 2: prior samples are values[:2] = [10, 100], geomean = sqrt(10*100) =
    # ~31.62 MPN -- reported as a multiple of the culture action value, so /104.
    expected_geomean_row2 = (
        10 ** ((math.log10(10) + math.log10(100)) / 2)
    ) / CULTURE_ENTEROCOCCUS_STV
    assert math.isclose(
        float(geomean.iloc[2]["enterococcus_action_ratio_geomean_30d_lagged"]),
        expected_geomean_row2,
        rel_tol=1e-9,
    )

    # Row 6: prior samples are values[:6] = [10, 100, 50, 200, 35, 1000], geomean
    # = 10 ** mean(log10) = 10 ** 1.957 ≈ 90.6.
    log_mean_row6 = np.mean([math.log10(v) for v in history_values[:6]])
    expected_geomean_row6 = (10 ** log_mean_row6) / CULTURE_ENTEROCOCCUS_STV
    assert math.isclose(
        float(geomean.iloc[6]["enterococcus_action_ratio_geomean_30d_lagged"]),
        expected_geomean_row6,
        rel_tol=1e-9,
    )

    # Threshold flags: 10 ** 1.957 = ~90.6 MPN -> exceeds 35 (yes) but not 104
    # (no). UNCHANGED by the ratio rescale on a culture beach: dividing the
    # geomean by 104 and the trigger by 104 leaves the same comparison, which is
    # why this fix is inert everywhere except beaches that report by ddPCR.
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

    last_row_geomean = float(geomean.iloc[-1]["enterococcus_action_ratio_geomean_30d_lagged"])
    # Window for last row should contain only the six 10.0 samples; geomean = 10
    # MPN, i.e. 10/104 of the culture action value.
    assert math.isclose(last_row_geomean, 10.0 / CULTURE_ENTEROCOCCUS_STV, rel_tol=1e-9)
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


# ---------------------------------------------------------------------------
# San Diego boundary-condition cohort flags + physical interactions.
# Research lineage: docs/superpowers/plans/2026-05-09-unstable-beaches-action-plan.md
# Implementation lineage: docs/superpowers/plans/2026-05-10-san-diego-boundary-features.md
# ---------------------------------------------------------------------------


def _boundary_row(beach_id: str, **overrides) -> pd.DataFrame:
    base = {
        "beach_id": beach_id,
        "sample_date": "2026-07-15",  # mid-summer (south-swell season)
        "sample_time": "2026-07-15T08:00:00-07:00",
        "enterococcus_value": 12.0,
        "exceeds_stv": 0,
        "wave_height_m": 1.0,
        "dominant_period_s": 10.0,
        "wave_direction_deg": 200.0,
        "water_temperature_c": 18.0,
        "salinity_psu": 33.0,
        "uv_index": 7.0,
        "wind_speed_mps": 3.0,
        "precip_mm_24h": 0.0,
        "precip_mm_72h": 0.0,
    }
    base.update(overrides)
    return pd.DataFrame([base])


SOUTH_SD_BEACH_IDS = [
    "ca068221-san-diego-imperial-beach-municipal-beach-other-ib-050",
    "ca432983-san-diego-imperial-beach-pier-area-eh-030",
    "ca134387-san-diego-north-imperial-beach-ib-060",
    "ca204955-san-diego-coronado-city-beaches-ib-079",
    "ca604254-san-diego-coronado-north-beach-eh-062",
    "ca801475-san-diego-silver-strand-state-beach-ib-069",
]

OCEANSIDE_BEACH_IDS = [
    "ca333308-san-diego-oceanside-municipal-beach-other-oc-040",
    "ca976061-san-diego-buccaneer-beach-oc-022",
]

CARDIFF_BEACH_IDS = [
    "ca152716-san-diego-cardiff-state-beach-se-050",
]


def test_south_sd_beaches_get_transboundary_and_south_swell_flags():
    """Imperial Beach / Coronado / Silver Strand are subject to the Tijuana sewage
    plume, the seasonal south-swell northward transport, and chronic dry-weather
    contamination. The cohort flags must all fire for these beach IDs."""
    for beach_id in SOUTH_SD_BEACH_IDS:
        enriched = add_temporal_features(_boundary_row(beach_id))
        assert enriched.iloc[0]["transboundary_sewage_exposure_flag"] == 1, beach_id
        assert enriched.iloc[0]["south_swell_sensitive_flag"] == 1, beach_id
        assert enriched.iloc[0]["dry_weather_contamination_zone_flag"] == 1, beach_id


def test_oceanside_beaches_get_engineered_protection_flags():
    """Oceanside / Buccaneer enjoy the Loma Alta Creek UV treatment facility plus
    the deep-ocean outfall, so they get the engineered-runoff protection flag."""
    for beach_id in OCEANSIDE_BEACH_IDS:
        enriched = add_temporal_features(_boundary_row(beach_id))
        assert enriched.iloc[0]["engineered_runoff_protection_flag"] == 1, beach_id
        assert enriched.iloc[0]["uv_treatment_protected_flag"] == 1, beach_id


def test_cardiff_state_beach_gets_lagoon_barrier_flag():
    """Cardiff State Beach is barricaded by the San Elijo Lagoon inlet, which
    frequently closes due to sand accumulation."""
    for beach_id in CARDIFF_BEACH_IDS:
        enriched = add_temporal_features(_boundary_row(beach_id))
        assert enriched.iloc[0]["lagoon_mouth_barrier_flag"] == 1, beach_id


def test_non_sd_beaches_get_zero_boundary_flags():
    """Beaches outside the named SD cohorts should have all boundary flags == 0."""
    out_of_cohort_ids = [
        "ca-other-malibu-pl-100",
        "ca068221-san-diego-imperial-beach-municipal-beach-other-eh-010",  # is south, sanity check below
        "ca789152-san-diego-carlsbad-municipal-beach-eh-470",
    ]
    # Carlsbad and a non-existent beach should have all zeros.
    for beach_id in ["ca-other-malibu-pl-100", "ca789152-san-diego-carlsbad-municipal-beach-eh-470"]:
        enriched = add_temporal_features(_boundary_row(beach_id))
        for flag in SD_BOUNDARY_FLAG_COLUMNS:
            assert enriched.iloc[0][flag] == 0, f"{beach_id} should not have {flag}=1"
    # And confirm a south-SD beach in the cohort does fire (positive control).
    enriched = add_temporal_features(_boundary_row(out_of_cohort_ids[1]))
    assert enriched.iloc[0]["transboundary_sewage_exposure_flag"] == 1


def test_south_sewage_dry_weather_interaction_is_high_when_dry():
    """transboundary_sewage_exposure_flag * (1 - precip/max_precip) — dry days
    at south-SD should produce a high interaction value."""
    row_dry = add_temporal_features(
        _boundary_row(SOUTH_SD_BEACH_IDS[0], precip_mm_24h=0.0, precip_mm_72h=0.0)
    )
    row_wet = add_temporal_features(
        _boundary_row(SOUTH_SD_BEACH_IDS[0], precip_mm_24h=40.0, precip_mm_72h=80.0)
    )
    assert (
        row_dry.iloc[0]["south_sewage_dry_weather_interaction"]
        > row_wet.iloc[0]["south_sewage_dry_weather_interaction"]
    )
    # Non-SD beaches should always have 0 for this column.
    non_sd = add_temporal_features(_boundary_row("ca-other-malibu-pl-100", precip_mm_24h=0.0))
    assert non_sd.iloc[0]["south_sewage_dry_weather_interaction"] == 0.0


def test_south_swell_season_interaction_lights_in_summer_only():
    """transboundary_sewage_exposure_flag * is_summer. Mid-July is summer; mid-Jan is not."""
    summer = add_temporal_features(_boundary_row(SOUTH_SD_BEACH_IDS[0], sample_date="2026-07-15"))
    winter = add_temporal_features(_boundary_row(SOUTH_SD_BEACH_IDS[0], sample_date="2026-01-15"))
    assert summer.iloc[0]["south_swell_season_interaction"] == 1
    assert winter.iloc[0]["south_swell_season_interaction"] == 0
    non_sd = add_temporal_features(_boundary_row("ca-other-malibu-pl-100", sample_date="2026-07-15"))
    assert non_sd.iloc[0]["south_swell_season_interaction"] == 0


def test_protected_north_rain_interaction_lights_only_for_oceanside_in_rain():
    """engineered_runoff_protection_flag * precip_mm_24h. Should be > 0 only for
    Oceanside/Buccaneer on a wet day."""
    wet = add_temporal_features(_boundary_row(OCEANSIDE_BEACH_IDS[0], precip_mm_24h=20.0))
    dry = add_temporal_features(_boundary_row(OCEANSIDE_BEACH_IDS[0], precip_mm_24h=0.0))
    south_wet = add_temporal_features(_boundary_row(SOUTH_SD_BEACH_IDS[0], precip_mm_24h=20.0))
    assert wet.iloc[0]["protected_north_rain_interaction"] == 20.0
    assert dry.iloc[0]["protected_north_rain_interaction"] == 0.0
    assert south_wet.iloc[0]["protected_north_rain_interaction"] == 0.0


def test_cardiff_lagoon_rain_interaction_lights_only_for_cardiff_in_rain():
    """lagoon_mouth_barrier_flag * precip_mm_24h. Only Cardiff in rain should fire."""
    wet = add_temporal_features(_boundary_row(CARDIFF_BEACH_IDS[0], precip_mm_24h=15.0))
    south_wet = add_temporal_features(_boundary_row(SOUTH_SD_BEACH_IDS[0], precip_mm_24h=15.0))
    assert wet.iloc[0]["cardiff_lagoon_rain_interaction"] == 15.0
    assert south_wet.iloc[0]["cardiff_lagoon_rain_interaction"] == 0.0


# ---------------------------------------------------------------------------
# Regime-resolved south-SD plume features (Kim, Terrill & Cornuelle 2009,
# Environ. Sci. Technol. 43:7450). The 2009 hindcast decomposes "Tijuana
# contamination" into three physically distinct sources with different
# triggers: TJR (rain-driven, wet season, northward transport), SBO (weak
# winter stratification → plume surfacing), PBD (continuous dry-weather,
# upcoast transport). These tests pin each regime to its trigger so the model
# sees three differentiated signals instead of the prior three identical flags.
# ---------------------------------------------------------------------------
def test_south_alongshore_wind_is_northward_for_southerly_wind():
    """south_alongshore_wind_ms: +ve = upcoast (northward) transport toward
    Imperial Beach / Coronado — the paper's core advection mechanism. A wind
    blowing FROM the south (met dir 180°) pushes plume water north → positive;
    a wind FROM the north (0°) → negative. Non-SD beaches stay at 0."""
    southerly = add_temporal_features(
        _boundary_row(
            SOUTH_SD_BEACH_IDS[0], wind_direction_24h_mean=180.0, wind_speed_24h_max=6.0
        )
    )
    northerly = add_temporal_features(
        _boundary_row(
            SOUTH_SD_BEACH_IDS[0], wind_direction_24h_mean=0.0, wind_speed_24h_max=6.0
        )
    )
    assert southerly.iloc[0]["south_alongshore_wind_ms"] > 0
    assert northerly.iloc[0]["south_alongshore_wind_ms"] < 0
    # Magnitude ≈ wind speed when wind is purely meridional.
    assert math.isclose(southerly.iloc[0]["south_alongshore_wind_ms"], 6.0, abs_tol=1e-6)
    non_sd = add_temporal_features(
        _boundary_row(
            "ca-other-malibu-pl-100", wind_direction_24h_mean=180.0, wind_speed_24h_max=6.0
        )
    )
    assert non_sd.iloc[0]["south_alongshore_wind_ms"] == 0.0


def test_tjr_wet_plume_interaction_high_in_wet_season_with_rain():
    """tjr_wet_plume_interaction: TJR is the rain-driven, wet-season source.
    Fires for south-SD beaches only when it is the wet season AND multi-day
    rain is present. Dry days, the summer dry season, and non-SD beaches all
    produce 0."""
    wet_winter = add_temporal_features(
        _boundary_row(SOUTH_SD_BEACH_IDS[0], sample_date="2026-01-15", precip_mm_72h=80.0)
    )
    dry_winter = add_temporal_features(
        _boundary_row(SOUTH_SD_BEACH_IDS[0], sample_date="2026-01-15", precip_mm_72h=0.0)
    )
    wet_summer = add_temporal_features(
        _boundary_row(SOUTH_SD_BEACH_IDS[0], sample_date="2026-07-15", precip_mm_72h=80.0)
    )
    assert wet_winter.iloc[0]["tjr_wet_plume_interaction"] > 0
    assert dry_winter.iloc[0]["tjr_wet_plume_interaction"] == 0.0
    assert wet_summer.iloc[0]["tjr_wet_plume_interaction"] == 0.0
    non_sd = add_temporal_features(
        _boundary_row("ca-other-malibu-pl-100", sample_date="2026-01-15", precip_mm_72h=80.0)
    )
    assert non_sd.iloc[0]["tjr_wet_plume_interaction"] == 0.0


def test_sbo_weak_stratification_interaction_winter_and_mixed_only():
    """sbo_weak_stratification_interaction: the South Bay Ocean Outfall plume
    surfaces only under weak stratification, which in the paper is a winter
    (418 days) vs summer (2 days) phenomenon driven by wind mixing. Fires for
    south-SD beaches in the wet season when wind mixing is present; summer,
    calm winter, and non-SD beaches produce 0."""
    winter_mixed = add_temporal_features(
        _boundary_row(SOUTH_SD_BEACH_IDS[0], sample_date="2026-01-15", wind_speed_24h_max=8.0)
    )
    winter_calm = add_temporal_features(
        _boundary_row(SOUTH_SD_BEACH_IDS[0], sample_date="2026-01-15", wind_speed_24h_max=0.0)
    )
    summer_mixed = add_temporal_features(
        _boundary_row(SOUTH_SD_BEACH_IDS[0], sample_date="2026-07-15", wind_speed_24h_max=8.0)
    )
    assert winter_mixed.iloc[0]["sbo_weak_stratification_interaction"] > 0
    assert winter_calm.iloc[0]["sbo_weak_stratification_interaction"] == 0.0
    assert summer_mixed.iloc[0]["sbo_weak_stratification_interaction"] == 0.0
    non_sd = add_temporal_features(
        _boundary_row("ca-other-malibu-pl-100", sample_date="2026-01-15", wind_speed_24h_max=8.0)
    )
    assert non_sd.iloc[0]["sbo_weak_stratification_interaction"] == 0.0


def test_boundary_flag_and_interaction_columns_appear_in_sliding_window_dataset():
    """All boundary columns must reach the model feature matrix."""
    values = [25.0 + 10.0 * (i % 3) for i in range(40)]
    frame = _make_history(SOUTH_SD_BEACH_IDS[0], "2026-04-01", values)
    dataset = build_sliding_windows(frame)
    feature_columns = set(dataset.feature_frame.columns)
    for column in SD_BOUNDARY_FLAG_COLUMNS + SD_BOUNDARY_INTERACTION_COLUMNS:
        assert column in feature_columns, f"{column} missing from sliding-window feature frame"
