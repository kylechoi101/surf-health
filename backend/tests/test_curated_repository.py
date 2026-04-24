import json

import pandas as pd

from app.repositories.curated_repository import CuratedBeachRepository


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
    assert forecast.lower_prediction_interval is None
    assert forecast.upper_prediction_interval is None
    observations = repository.get_observations("ca123-orange-main-beach-main-beach-pier")
    assert len(observations.observations) == 1
    assert len(observations.advisories) == 1
