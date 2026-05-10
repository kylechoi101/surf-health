from datetime import UTC, date, datetime

from app.schemas.domain import ForecastRecord


def test_forecast_record_honest_metadata_defaults_are_backward_compatible():
    forecast = ForecastRecord(
        beach_id="alpha",
        forecast_date=date(2026, 4, 20),
        risk_band="Moderate",
        p_exceed=0.34,
        model_version="hist-gbm-curated-v0",
        forecast_generated_at=datetime(2026, 4, 20, 13, tzinfo=UTC),
    )

    assert forecast.forecast_label_mode == "model"
    assert forecast.sample_age_days is None
    assert forecast.sample_recency_band == "unknown"
    assert forecast.is_beta_forecast is True
