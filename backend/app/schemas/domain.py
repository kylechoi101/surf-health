from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


RiskBand = Literal["Low", "Moderate", "High", "Very High", "Advisory"]
SupportStatus = Literal["production", "beta", "unsupported"]
ForecastLabelMode = Literal[
    "model",
    "official_advisory_override",
    "derived_persistence",
    "unavailable",
]
SampleRecencyBand = Literal["fresh", "recent", "stale", "very_stale", "unknown"]

# Serve-time staleness cap for forecast rows. Anything older than this (or of
# unknowable age on a fallback row) is flagged is_stale=True so clients render
# a degraded state instead of presenting a days-old band as today's answer.
# Records are still served — degrade honestly, never refuse and never present
# stale data as current.
MAX_FORECAST_AGE_HOURS = 48


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
    # Display name — typically the parent's name when this station rolls up
    # into a parent group, otherwise the local station name.
    name: str
    # Local station nickname (e.g. "Black's Beach" for the FM-090 station
    # under "Torrey Pines State Beach"). Apps match search queries against
    # this so users can find a station by the name they know it by.
    station_name: str | None = None
    # Human-readable beach name from the curated roster (e.g. "Huntington
    # State Beach"). Sits alongside `name` (which is typically the cryptic
    # sampling-station label like "50' N of Santa Ana River"). Apps prefer
    # this for display when available. Optional because legacy serving
    # snapshots and fixtures may not carry the column.
    beach_name: str | None = None
    # Beachwatch sampling-station code (e.g. "FM-090", "15N", "1000"). Shown
    # in the apps as a compact monospace chip beside the consolidated beach
    # name. Optional because legacy serving snapshots may not carry it.
    station_code: str | None = None
    county: str
    region: str
    support_status: SupportStatus
    model_version: str | None = None
    latest_official_sample_at: datetime | None = None
    geometry: Point
    # Compass bearing (deg, 0=N, clockwise) pointing FROM the beach OUT TO SEA.
    # Used by the apps to tag the current wind as onshore / offshore / cross-
    # shore. Optional because fixture payloads and legacy clients may not
    # populate it.
    shore_normal_deg: float | None = None


class ParentBeachSummary(BaseModel):
    id: str
    name: str
    county: str
    region: str
    support_status: SupportStatus
    model_version: str | None = None
    station_count: int
    member_beach_ids: list[str]
    # Local nicknames for each member station (e.g. "Black's Beach" for the
    # FM-090 station under the "Torrey Pines State Beach" parent). Apps
    # match search queries against these so users can find a parent by the
    # name they actually know it by, not just the official BeachWatch label.
    member_beach_names: list[str] = Field(default_factory=list)
    # Beachwatch station codes for each member, index-aligned with
    # member_beach_ids (empty string where a member has no code). Lets the
    # apps render the station-code chip for whichever member supplies the
    # parent's display name (e.g. the aliased "Black's Beach" → "FM-090").
    member_station_codes: list[str] = Field(default_factory=list)
    latest_official_sample_at: datetime | None = None
    geometry: Point
    risk_band: RiskBand | None = None
    p_exceed: float | None = None
    has_active_advisory: bool = False
    advisory_website: str | None = None
    # Number of member stations under this parent that have an active
    # advisory (e.g. "2 of 5 stations are posted"). The UI uses this to
    # explain at-a-glance why a parent card shows Advisory when only some
    # of its members are actually flagged. 0 when has_active_advisory is
    # false. Computed by the repositories per /beaches request.
    flagged_station_count: int = 0
    # Display names of the flagged member stations. Populated alongside
    # flagged_station_count so the future "station naming" spec can render
    # "Posted: Black's Beach, North Stairs" without another API round-trip.
    # Clients should NOT render this yet — it ships behind a future feature
    # flag once the naming polish (spec I) lands.
    flagged_station_names: list[str] = Field(default_factory=list)


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
    # None when the stored row predates the forecast_generated_at column.
    # Never fabricated at serve time — a fabricated "now" would defeat the
    # is_stale flag below by making every legacy row look freshly generated.
    forecast_generated_at: datetime | None = None
    forecast_age_hours: int | None = None
    # True when the forecast is older than MAX_FORECAST_AGE_HOURS, or when
    # its age is unknowable on a fallback (non-requested-date) row. Additive
    # and defaulted so existing clients that ignore unknown fields keep
    # working.
    is_stale: bool = False
    official_advisory_active: bool = False
    advisory_floor_applied: bool = False
    advisory_website: str | None = None
    # Parent-aware sibling-advisory signal: true when THIS station has no
    # active advisory but at least one other station under the same parent
    # beach (same beach_id prefix) does. The UI uses this to render a soft
    # "a related station is posted" callout so users aren't confused when
    # the parent card shows Advisory but the specific station they tapped
    # is Low.
    parent_has_active_advisory: bool = False
    parent_advisory_website: str | None = None
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
