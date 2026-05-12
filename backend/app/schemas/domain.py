from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


RiskBand = Literal["Low", "Moderate", "High", "Very High"]
SupportStatus = Literal["production", "beta", "unsupported"]
ForecastLabelMode = Literal[
    "model",
    "official_advisory_override",
    "derived_persistence",
    "unavailable",
]
SampleRecencyBand = Literal["fresh", "recent", "stale", "very_stale", "unknown"]


def sample_recency_band(sample_age_days: int | None) -> SampleRecencyBand:
    if sample_age_days is None:
        return "unknown"
    if sample_age_days <= 3:
        return "fresh"
    if sample_age_days <= 20:
        return "recent"
    if sample_age_days <= 60:
        return "stale"
    return "very_stale"


class Point(BaseModel):
    latitude: float
    longitude: float


class EnvironmentalSummary(BaseModel):
    wave_height_m: float | None = None
    dominant_period_s: float | None = None
    water_temperature_c: float | None = None
    salinity_psu: float | None = None
    uv_index: float | None = None
    wind_speed_mps: float | None = None
    wind_direction_deg: float | None = None


class BeachSummary(BaseModel):
    id: str
    name: str
    county: str
    region: str
    support_status: SupportStatus
    model_version: str | None = None
    latest_official_sample_at: datetime | None = None
    geometry: Point


class ParentBeachSummary(BaseModel):
    id: str
    name: str
    county: str
    region: str
    support_status: SupportStatus
    model_version: str | None = None
    station_count: int
    member_beach_ids: list[str]
    latest_official_sample_at: datetime | None = None
    geometry: Point
    risk_band: RiskBand | None = None
    p_exceed: float | None = None
    has_active_advisory: bool = False
    advisory_website: str | None = None


class ForecastRecord(BaseModel):
    beach_id: str
    forecast_date: date
    risk_band: RiskBand
    model_risk_band: RiskBand | None = None
    p_exceed: float = Field(ge=0.0, le=1.0)
    p_exceed_raw: float | None = Field(default=None, ge=0.0, le=1.0)
    p_exceed_lower: float | None = Field(default=None, ge=0.0, le=1.0)
    p_exceed_upper: float | None = Field(default=None, ge=0.0, le=1.0)
    predicted_log_enterococcus: float | None = None
    lower_prediction_interval: float | None = None
    upper_prediction_interval: float | None = None
    prediction_interval_level: float | None = Field(default=None, ge=0.0, le=1.0)
    top_drivers: list[str] = Field(default_factory=list)
    model_version: str
    forecast_generated_at: datetime
    forecast_age_hours: int | None = None
    official_advisory_active: bool = False
    advisory_floor_applied: bool = False
    forecast_label_mode: ForecastLabelMode = "model"
    sample_age_days: int | None = Field(default=None, ge=0)
    sample_recency_band: SampleRecencyBand = "unknown"
    is_beta_forecast: bool = True
    environmental_summary: EnvironmentalSummary = Field(default_factory=EnvironmentalSummary)


class ObservationRecord(BaseModel):
    sample_time: datetime
    analyte: str
    method: str
    units: str
    value: float
    exceeds_stv: bool


class AdvisoryRecord(BaseModel):
    advisory_type: str
    started_at: datetime
    ended_at: datetime | None = None
    status: str
    advisory_website: str | None = None


class ObservationResponse(BaseModel):
    beach_id: str
    observations: list[ObservationRecord]
    advisories: list[AdvisoryRecord]
    recent_environment: list[dict[str, Any]]


class SystemHealthResponse(BaseModel):
    app_env: str
    is_beta_product: bool = True
    pipeline_freshness: str
    source_freshness: dict[str, str]
    model_registry: dict[str, Any]
    active_advisories_count: int | None = None
    forecast_audit: dict[str, Any] | None = None
    repository_mode: str | None = None
    serving_snapshot: dict[str, Any] | None = None


class ForecastExplanationRequest(BaseModel):
    beach_name: str
    forecast: ForecastRecord


class ForecastExplanationResponse(BaseModel):
    beach_id: str
    summary: str
    used_model: str
