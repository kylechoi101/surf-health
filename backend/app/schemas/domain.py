from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


RiskBand = Literal["Low", "Moderate", "High", "Very High"]
SupportStatus = Literal["production", "beta", "unsupported"]


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
    latest_official_sample_at: datetime | None = None
    geometry: Point


class ForecastRecord(BaseModel):
    beach_id: str
    forecast_date: date
    risk_band: RiskBand
    p_exceed: float = Field(ge=0.0, le=1.0)
    predicted_log_enterococcus: float | None = None
    lower_prediction_interval: float | None = None
    upper_prediction_interval: float | None = None
    prediction_interval_level: float | None = Field(default=None, ge=0.0, le=1.0)
    top_drivers: list[str] = Field(default_factory=list)
    model_version: str
    forecast_generated_at: datetime
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


class ObservationResponse(BaseModel):
    beach_id: str
    observations: list[ObservationRecord]
    advisories: list[AdvisoryRecord]
    recent_environment: list[dict[str, Any]]


class SystemHealthResponse(BaseModel):
    app_env: str
    pipeline_freshness: str
    source_freshness: dict[str, str]
    model_registry: dict[str, Any]


class ForecastExplanationRequest(BaseModel):
    beach_name: str
    forecast: ForecastRecord


class ForecastExplanationResponse(BaseModel):
    beach_id: str
    summary: str
    used_model: str
