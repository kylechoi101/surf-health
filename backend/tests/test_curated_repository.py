import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa

from app.repositories.curated_repository import CuratedBeachRepository, _safe_bool


class TestSafeBool:
    def test_true_values(self):
        assert _safe_bool(True) is True
        assert _safe_bool(1) is True
        assert _safe_bool("1") is True
        assert _safe_bool("true") is True
        assert _safe_bool("True") is True
        assert _safe_bool("yes") is True

    def test_false_values(self):
        assert _safe_bool(False) is False
        assert _safe_bool(0) is False
        assert _safe_bool("0") is False
        assert _safe_bool("false") is False
        assert _safe_bool("False") is False
        assert _safe_bool("") is False

    def test_none_default_true(self):
        assert _safe_bool(None, default=True) is True

    def test_none_default_false(self):
        assert _safe_bool(None, default=False) is False


def test_curated_repository_derives_forecast_and_observations(tmp_path):
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()
    pd.DataFrame(
        [
            {
                "beach_id": "ca123-orange-main-beach-main-beach-pier",
                "name": "Main Beach Pier",
                "county": "Orange",
                "region": "Santa Ana",
                "support_status": "production",
                "latest_official_sample_at": "2026-04-18T08:00:00",
                "latitude": 33.5,
                "longitude": -117.8,
                "usepa_id": "CA123",
                "water_body_class": "Saltwater",
                "water_body_type": "Open Coast",
                "agency_name": "County Lab",
            }
        ]
    ).to_parquet(curated_dir / "beaches.parquet", index=False)
    pd.DataFrame(
        [
            {
                "beach_id": "ca123-orange-main-beach-main-beach-pier",
                "sample_time": "2026-04-18T08:00:00",
                "sample_date": "2026-04-18",
                "analyte": "enterococcus",
                "method": "Culture",
                "units": "CFU/100ml",
                "value": 120.0,
                "exceeds_stv": True,
                "county": "Orange",
                "station_name": "Main Beach Pier",
                "beach_name": "Main Beach",
                "usepa_id": "CA123",
                "weather": "Sunny",
                "storm_drain_flow": "No",
                "tidal_height": 1.2,
                "surf_height_observed": 2.0,
                "turbidity_observed": 5.0,
                "odor": "None",
                "water_color": "Blue",
            }
        ]
    ).to_parquet(curated_dir / "observations.parquet", index=False)
    pd.DataFrame(
        [
            {
                "beach_id": "ca123-orange-main-beach-main-beach-pier",
                "advisory_type": "Posting",
                "started_at": "2026-04-18T10:30:00",
                "ended_at": None,
                "status": "historical",
                "cause": "Unknown Cause",
                "county": "Orange",
            }
        ]
    ).to_parquet(curated_dir / "advisories.parquet", index=False)
    pd.DataFrame(
        [
            {
                "beach_id": "ca123-orange-main-beach-main-beach-pier",
                "sample_date": "2026-04-18",
                "sample_time": "2026-04-18T08:00:00",
                "enterococcus_value": 120.0,
                "exceeds_stv": True,
                "weather": "Sunny",
                "storm_drain_flow": "No",
                "tidal_height": 1.2,
                "surf_height_observed": 2.0,
                "turbidity_observed": 5.0,
                "odor": "None",
                "water_color": "Blue",
                "name": "Main Beach Pier",
                "county": "Orange",
                "region": "Santa Ana",
                "latitude": 33.5,
                "longitude": -117.8,
                "support_status": "production",
                "usepa_id": "CA123",
                "water_body_class": "Saltwater",
                "water_body_type": "Open Coast",
                "agency_name": "County Lab",
                "historical_advisory_count": 1,
            }
        ]
    ).to_parquet(curated_dir / "beach_day.parquet", index=False)
    (curated_dir / "system_health.json").write_text(
        json.dumps(
            {
                "pipeline_freshness": "2026-04-20T05:00:00Z",
                "source_freshness": {"observations": "2026-04-20T05:00:00Z"},
                "model_registry": {
                    "production_model": "derived-persistence-v0",
                    "candidate_models": [],
                    "metrics": {},
                },
            }
        )
    )

    repository = CuratedBeachRepository(curated_dir, stv_threshold=104.0)
    beaches = repository.list_beaches()
    assert len(beaches) == 1
    forecast = repository.get_forecast(
        "ca123-orange-main-beach-main-beach-pier",
        forecast_date=pd.Timestamp("2026-04-20").date(),
    )
    assert forecast.p_exceed > 0.5
    assert forecast.forecast_label_mode == "derived_persistence"
    assert forecast.sample_age_days == 2
    assert forecast.sample_recency_band == "fresh"
    assert forecast.is_beta_forecast is True
    assert forecast.lower_prediction_interval is None
    assert forecast.upper_prediction_interval is None
    observations = repository.get_observations("ca123-orange-main-beach-main-beach-pier")
    assert len(observations.observations) == 1
    assert len(observations.advisories) == 1
    assert repository.get_system_health().is_beta_product is True


def test_curated_repository_overrides_forecast_when_official_advisory_active(tmp_path):
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()
    beach_id = "ca123-orange-main-beach-main-beach-pier"
    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "forecast_date": "2026-04-20",
                "risk_band": "High",
                "p_exceed": 0.30,
                "p_exceed_raw": 0.08,
                "advisory_floor_applied": True,
                "predicted_log_enterococcus": 1.2,
                "lower_prediction_interval": 0.9,
                "upper_prediction_interval": 1.7,
                "prediction_interval_level": 0.9,
                "top_drivers": ["model signal"],
                "model_version": "hist-gbm-v1",
                "forecast_generated_at": "2026-04-20T13:00:00+00:00",
            }
        ]
    ).to_parquet(curated_dir / "forecasts.parquet", index=False)
    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "advisory_type": "Posting",
                "started_at": "2026-04-20T10:30:00",
                "ended_at": None,
                "status": "active",
            }
        ]
    ).to_parquet(curated_dir / "advisories.parquet", index=False)

    repository = CuratedBeachRepository(curated_dir, stv_threshold=104.0)
    forecast = repository.get_forecast(beach_id, date(2026, 4, 20))

    assert forecast.official_advisory_active is True
    assert forecast.risk_band == "Very High"
    assert forecast.model_risk_band == "Low"
    assert forecast.forecast_label_mode == "official_advisory_override"
    assert forecast.advisory_floor_applied is True
    assert forecast.top_drivers == [
        "Official health advisory is active for this station.",
        "model signal",
    ]
    assert forecast.p_exceed == 0.30
    assert forecast.p_exceed_raw == 0.08


def test_curated_repository_overrides_derived_forecast_when_official_advisory_active(tmp_path):
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()
    beach_id = "ca123-orange-main-beach-main-beach-pier"
    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "sample_time": "2026-04-18T08:00:00",
                "sample_date": "2026-04-18",
                "analyte": "enterococcus",
                "method": "Culture",
                "units": "CFU/100ml",
                "value": 120.0,
                "exceeds_stv": True,
                "weather": "Sunny",
                "storm_drain_flow": "No",
            }
        ]
    ).to_parquet(curated_dir / "observations.parquet", index=False)
    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "advisory_type": "Posting",
                "started_at": "2026-04-18T10:30:00",
                "ended_at": None,
                "status": "active",
            }
        ]
    ).to_parquet(curated_dir / "advisories.parquet", index=False)

    repository = CuratedBeachRepository(curated_dir, stv_threshold=104.0)
    forecast = repository.get_forecast(beach_id, date(2026, 4, 20))

    assert forecast.official_advisory_active is True
    assert forecast.risk_band == "Very High"
    assert forecast.model_risk_band == "High"
    assert forecast.forecast_label_mode == "official_advisory_override"
    assert forecast.top_drivers[0] == "Official health advisory is active for this station."
    assert "above the marine threshold" in forecast.top_drivers[1]


def test_curated_repository_does_not_derive_forecast_from_stale_sample(tmp_path):
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()
    beach_id = "ca123-orange-main-beach-main-beach-pier"
    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "sample_time": "2026-01-01T08:00:00",
                "sample_date": "2026-01-01",
                "analyte": "enterococcus",
                "method": "Culture",
                "units": "CFU/100ml",
                "value": 140.0,
                "exceeds_stv": True,
            }
        ]
    ).to_parquet(curated_dir / "observations.parquet", index=False)

    repository = CuratedBeachRepository(curated_dir, stv_threshold=104.0)

    try:
        repository.get_forecast(beach_id, date(2026, 4, 20))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 404
        assert "fresh" in str(getattr(exc, "detail", "")).lower()
    else:
        raise AssertionError("stale samples must not produce derived persistence forecasts")


def test_curated_repository_limits_parquet_columns_for_per_beach_reads(monkeypatch, tmp_path):
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()
    (curated_dir / "observations.parquet").write_bytes(b"placeholder")
    (curated_dir / "beach_day.parquet").write_bytes(b"placeholder")
    pd.DataFrame(
        columns=["beach_id", "advisory_type", "started_at", "ended_at", "status"]
    ).to_parquet(curated_dir / "advisories.parquet", index=False)

    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake_read_table(path, *, filters, columns=None):
        calls.append((Path(path).name, tuple(columns or ())))
        beach_id = filters[0][2]
        if Path(path).name == "observations.parquet":
            return pa.table(
                {
                    "beach_id": [beach_id],
                    "sample_time": ["2026-04-18T08:00:00"],
                    "sample_date": ["2026-04-18"],
                    "analyte": ["enterococcus"],
                    "method": ["Culture"],
                    "units": ["CFU/100ml"],
                    "value": [120.0],
                    "exceeds_stv": [True],
                    "weather": ["Sunny"],
                    "storm_drain_flow": ["No"],
                }
            )
        return pa.table(
            {
                "beach_id": [beach_id],
                "sample_date": ["2026-04-18"],
                "wave_height_m": [1.1],
                "dominant_period_s": [8.0],
                "water_temperature_c": [16.2],
                "salinity_psu": [33.0],
                "weather": ["Sunny"],
                "storm_drain_flow": ["No"],
                "tidal_height": [1.2],
                "surf_height_observed": [2.0],
                "turbidity_observed": [5.0],
            }
        )

    monkeypatch.setattr("app.repositories.curated_repository.pq.read_table", fake_read_table)

    repository = CuratedBeachRepository(curated_dir, stv_threshold=104.0)
    repository.__dict__["advisories_frame"] = pd.DataFrame(
        columns=["beach_id", "advisory_type", "started_at", "ended_at", "status"]
    )
    repository.get_forecast("ca123-orange-main-beach-main-beach-pier", pd.Timestamp("2026-04-20").date())
    repository._beach_day_for_beach("ca123-orange-main-beach-main-beach-pier")

    assert calls == [
        (
            "observations.parquet",
            (
                "beach_id",
                "sample_time",
                "sample_date",
                "analyte",
                "method",
                "units",
                "value",
                "exceeds_stv",
                "weather",
                "storm_drain_flow",
            ),
        ),
        (
            "beach_day.parquet",
            (
                "beach_id",
                "sample_date",
                "wave_height_m",
                "dominant_period_s",
                "water_temperature_c",
                "salinity_psu",
                "weather",
                "storm_drain_flow",
                "tidal_height",
                "surf_height_observed",
                "turbidity_observed",
            ),
        ),
    ]


def test_curated_repository_caches_per_beach_observation_reads(monkeypatch, tmp_path):
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()
    (curated_dir / "observations.parquet").write_bytes(b"placeholder")
    (curated_dir / "beach_day.parquet").write_bytes(b"placeholder")
    pd.DataFrame(
        columns=["beach_id", "advisory_type", "started_at", "ended_at", "status"]
    ).to_parquet(curated_dir / "advisories.parquet", index=False)

    calls: list[str] = []

    def fake_read_table(path, *, filters, columns=None):
        calls.append(Path(path).name)
        beach_id = filters[0][2]
        if Path(path).name == "observations.parquet":
            return pa.table(
                {
                    "beach_id": [beach_id],
                    "sample_time": ["2026-04-18T08:00:00"],
                    "sample_date": ["2026-04-18"],
                    "analyte": ["enterococcus"],
                    "method": ["Culture"],
                    "units": ["CFU/100ml"],
                    "value": [120.0],
                    "exceeds_stv": [True],
                    "weather": ["Sunny"],
                    "storm_drain_flow": ["No"],
                }
            )
        return pa.table(
            {
                "beach_id": [beach_id],
                "sample_date": ["2026-04-18"],
                "wave_height_m": [1.1],
                "dominant_period_s": [8.0],
                "water_temperature_c": [16.2],
                "salinity_psu": [33.0],
                "weather": ["Sunny"],
                "storm_drain_flow": ["No"],
                "tidal_height": [1.2],
                "surf_height_observed": [2.0],
                "turbidity_observed": [5.0],
            }
        )

    monkeypatch.setattr("app.repositories.curated_repository.pq.read_table", fake_read_table)

    repository = CuratedBeachRepository(curated_dir, stv_threshold=104.0)
    repository.__dict__["advisories_frame"] = pd.DataFrame(
        columns=["beach_id", "advisory_type", "started_at", "ended_at", "status"]
    )
    repository.get_observations("ca123-orange-main-beach-main-beach-pier")
    repository.get_observations("ca123-orange-main-beach-main-beach-pier")

    assert calls == ["observations.parquet", "beach_day.parquet"]


def test_curated_repository_coalesces_concurrent_per_beach_observation_reads(
    monkeypatch, tmp_path
):
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir()
    (curated_dir / "observations.parquet").write_bytes(b"placeholder")
    (curated_dir / "beach_day.parquet").write_bytes(b"placeholder")

    calls: list[str] = []

    def fake_read_table(path, *, filters, columns=None):
        calls.append(Path(path).name)
        time.sleep(0.05)
        beach_id = filters[0][2]
        if Path(path).name == "observations.parquet":
            return pa.table(
                {
                    "beach_id": [beach_id],
                    "sample_time": ["2026-04-18T08:00:00"],
                    "sample_date": ["2026-04-18"],
                    "analyte": ["enterococcus"],
                    "method": ["Culture"],
                    "units": ["CFU/100ml"],
                    "value": [120.0],
                    "exceeds_stv": [True],
                    "weather": ["Sunny"],
                    "storm_drain_flow": ["No"],
                }
            )
        return pa.table(
            {
                "beach_id": [beach_id],
                "sample_date": ["2026-04-18"],
                "wave_height_m": [1.1],
                "dominant_period_s": [8.0],
                "water_temperature_c": [16.2],
                "salinity_psu": [33.0],
                "weather": ["Sunny"],
                "storm_drain_flow": ["No"],
                "tidal_height": [1.2],
                "surf_height_observed": [2.0],
                "turbidity_observed": [5.0],
            }
        )

    monkeypatch.setattr("app.repositories.curated_repository.pq.read_table", fake_read_table)

    repository = CuratedBeachRepository(curated_dir, stv_threshold=104.0)
    repository.__dict__["advisories_frame"] = pd.DataFrame(
        columns=["beach_id", "advisory_type", "started_at", "ended_at", "status"]
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                repository.get_observations,
                ["ca123-orange-main-beach-main-beach-pier"] * 2,
            )
        )

    assert [len(result.observations) for result in results] == [1, 1]
    assert calls == ["observations.parquet", "beach_day.parquet"]
