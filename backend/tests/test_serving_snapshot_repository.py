import json
import sqlite3
from datetime import date
from types import SimpleNamespace

import pandas as pd

from app.data.pipeline.serving_snapshot import build_serving_snapshot
from app.repositories.factory import build_repository
from app.repositories.serving_repository import ServingSnapshotRepository


def _write_curated_inputs(curated_dir):
    curated_dir.mkdir()
    beach_id = "ca123-orange-main-beach-main-beach-pier"
    other_id = "ca999-orange-other-beach-other"

    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "name": "Main Beach Pier",
                "county": "Orange",
                "region": "Santa Ana",
                "support_status": "production",
                "latest_official_sample_at": "2026-04-18T08:00:00",
                "latitude": 33.5,
                "longitude": -117.8,
            },
            {
                "beach_id": other_id,
                "name": "Other Beach",
                "county": "Orange",
                "region": "Santa Ana",
                "support_status": "production",
                "latest_official_sample_at": "2026-04-18T08:00:00",
                "latitude": 33.6,
                "longitude": -117.9,
            },
        ]
    ).to_parquet(curated_dir / "beaches.parquet", index=False)

    pd.DataFrame(
        [
            {
                "parent_beach_id": "parent-ca123",
                "name": "Main Beach",
                "county": "Orange",
                "region": "Santa Ana",
                "support_status": "production",
                "latitude": 33.5,
                "longitude": -117.8,
                "station_count": 2,
                "member_beach_ids": [beach_id, other_id],
                "latest_official_sample_at": "2026-04-18T08:00:00",
            }
        ]
    ).to_parquet(curated_dir / "parent_beaches.parquet", index=False)

    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "forecast_date": "2026-04-20",
                "risk_band": "High",
                "p_exceed": 0.72,
                "predicted_log_enterococcus": 2.1,
                "lower_prediction_interval": 1.3,
                "upper_prediction_interval": 2.9,
                "prediction_interval_level": 0.9,
                "top_drivers": ["recent high sample", "waves elevated"],
                "model_version": "stacked-ensemble-curated-v0",
                "forecast_generated_at": "2026-04-20T13:00:00+00:00",
                "wave_height_m": 1.2,
                "dominant_period_s": 8.0,
                "water_temperature_c": 16.4,
                "salinity_psu": 33.1,
                "uv_index": 6.0,
            }
        ]
    ).to_parquet(curated_dir / "forecasts.parquet", index=False)

    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "wave_height_m": 1.1,
                "dominant_period_s": 8.0,
                "water_temperature_c": 16.2,
                "salinity_psu": 33.0,
                "uv_index": 5.0,
                "wind_speed_mps": 3.0,
                "wind_direction_deg": 220.0,
            }
        ]
    ).to_parquet(curated_dir / "latest_env.parquet", index=False)

    observations = []
    beach_days = []
    for idx in range(30):
        day = pd.Timestamp("2026-04-01") + pd.Timedelta(days=idx)
        observations.append(
            {
                "beach_id": beach_id,
                "sample_time": day.isoformat(),
                "sample_date": day.date().isoformat(),
                "analyte": "enterococcus",
                "method": "Culture",
                "units": "CFU/100ml",
                "value": float(20 + idx),
                "exceeds_stv": idx > 26,
                "weather": "Sunny",
                "storm_drain_flow": "No",
            }
        )
        beach_days.append(
            {
                "beach_id": beach_id,
                "sample_date": day.date().isoformat(),
                "wave_height_m": float(idx),
                "dominant_period_s": 8.0,
                "water_temperature_c": 16.0,
                "salinity_psu": 33.0,
                "weather": "Sunny",
                "storm_drain_flow": "No",
                "tidal_height": 1.0,
                "surf_height_observed": 2.0,
                "turbidity_observed": 5.0,
            }
        )
    pd.DataFrame(observations).to_parquet(curated_dir / "observations.parquet", index=False)
    pd.DataFrame(beach_days).to_parquet(curated_dir / "beach_day.parquet", index=False)

    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "advisory_type": "Posting",
                "started_at": "2026-04-18T10:30:00",
                "ended_at": None,
                "status": "active",
                "cause": "Unknown Cause",
                "county": "Orange",
            }
        ]
    ).to_parquet(curated_dir / "advisories.parquet", index=False)

    (curated_dir / "system_health.json").write_text(
        json.dumps(
            {
                "pipeline_freshness": "2026-04-20T05:00:00Z",
                "source_freshness": {"observations": "2026-04-20T05:00:00Z"},
                "model_registry": {
                    "production_model": "stacked-ensemble-curated-v0",
                    "candidate_models": [],
                    "metrics": {},
                },
            }
        )
    )

    return beach_id


def test_serving_snapshot_limits_hot_path_rows_and_repository_serves_contract(tmp_path):
    curated_dir = tmp_path / "curated"
    beach_id = _write_curated_inputs(curated_dir)
    snapshot_path = build_serving_snapshot(curated_dir)

    with sqlite3.connect(snapshot_path) as conn:
        assert conn.execute("select count(*) from observations_recent").fetchone()[0] == 25
        assert conn.execute("select count(*) from recent_environment").fetchone()[0] == 10

    repository = ServingSnapshotRepository(snapshot_path, stv_threshold=104.0)

    beach = repository.get_beach(beach_id)
    assert beach.name == "Main Beach"

    forecast = repository.get_forecast(beach_id, date(2026, 4, 20))
    assert forecast.risk_band == "High"
    assert forecast.environmental_summary.wave_height_m == 1.2

    observations = repository.get_observations(beach_id)
    assert len(observations.observations) == 25
    assert len(observations.recent_environment) == 10
    assert observations.observations[0].value == 49.0

    parents = repository.list_parent_beaches()
    assert parents[0].risk_band == "High"
    assert parents[0].has_active_advisory is True

    health = repository.get_system_health()
    assert health.active_advisories_count == 1


def test_repository_factory_prefers_serving_snapshot_when_present(tmp_path):
    curated_dir = tmp_path / "curated"
    _write_curated_inputs(curated_dir)
    build_serving_snapshot(curated_dir)
    for parquet_path in curated_dir.glob("*.parquet"):
        parquet_path.unlink()

    settings = SimpleNamespace(
        curated_dir=curated_dir,
        preferred_repository="curated",
        fixture_data_path=tmp_path / "missing.json",
        epa_marine_enterococcus_stv=104.0,
    )

    repository = build_repository(settings)

    assert isinstance(repository, ServingSnapshotRepository)
