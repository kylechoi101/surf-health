from datetime import UTC, date, datetime

from app.schemas.domain import ForecastRecord, SystemHealthResponse


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
    assert forecast.is_stale is False


def test_forecast_record_generated_at_is_optional_and_never_fabricated():
    """Legacy rows without forecast_generated_at must pass None through —
    the API is additive-only, so the field is optional/null, not invented."""
    forecast = ForecastRecord(
        beach_id="alpha",
        forecast_date=date(2026, 4, 20),
        risk_band="Moderate",
        p_exceed=0.34,
        model_version="hist-gbm-curated-v0",
    )

    assert forecast.forecast_generated_at is None
    assert forecast.forecast_age_hours is None
    assert forecast.is_stale is False
    assert forecast.model_dump(mode="json")["forecast_generated_at"] is None


def test_system_health_marks_product_as_beta_by_default():
    health = SystemHealthResponse(
        app_env="test",
        pipeline_freshness="2026-04-20T05:00:00Z",
        source_freshness={"observations": "2026-04-20T05:00:00Z"},
        model_registry={"production_model": "hist_gbm_positive_persistence_guard"},
    )

    assert health.is_beta_product is True
