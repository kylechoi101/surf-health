from __future__ import annotations

import json
import os
import re
from datetime import UTC, date, datetime
from functools import cached_property
from math import log10
from pathlib import Path

import pandas as pd
from fastapi import HTTPException

from app.ml.calibration import risk_band
from app.repositories.base import BeachRepository
from app.schemas.domain import (
    AdvisoryRecord,
    BeachSummary,
    EnvironmentalSummary,
    ForecastRecord,
    ObservationRecord,
    ObservationResponse,
    Point,
    SystemHealthResponse,
)


def _derive_friendly_name(row: object) -> str:
    beach_id = str(row["beach_id"])
    beach_id = re.sub(r"^ca\d+-", "", beach_id)
    county_slug = str(row.get("county", "")).lower().replace(" ", "-")
    if beach_id.startswith(county_slug + "-"):
        beach_id = beach_id[len(county_slug) + 1 :]
    station_raw = str(row.get("name", ""))
    station_slug = re.sub(r"[^a-z0-9]+", "-", station_raw.lower()).strip("-")
    if station_slug and beach_id.endswith("-" + station_slug):
        beach_id = beach_id[: -(len(station_slug) + 1)]
    return beach_id.replace("-", " ").title() if beach_id else station_raw


def _safe_float(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


class CuratedBeachRepository(BeachRepository):
    def __init__(self, curated_dir: Path, stv_threshold: float) -> None:
        self.curated_dir = curated_dir
        self.stv_threshold = stv_threshold

    @cached_property
    def beaches_frame(self) -> pd.DataFrame:
        return pd.read_parquet(self.curated_dir / "beaches.parquet")

    @cached_property
    def observations_frame(self) -> pd.DataFrame:
        return pd.read_parquet(self.curated_dir / "observations.parquet")

    @cached_property
    def advisories_frame(self) -> pd.DataFrame:
        path = self.curated_dir / "advisories.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    @cached_property
    def beach_day_frame(self) -> pd.DataFrame:
        path = self.curated_dir / "beach_day.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    @cached_property
    def forecasts_frame(self) -> pd.DataFrame:
        path = self.curated_dir / "forecasts.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    def list_beaches(self) -> list[BeachSummary]:
        beaches: list[BeachSummary] = []
        for _, row in self.beaches_frame.iterrows():
            beaches.append(
                BeachSummary(
                    id=row["beach_id"],
                    name=_derive_friendly_name(row),
                    county=row["county"],
                    region=row["region"],
                    support_status=row["support_status"],
                    latest_official_sample_at=(
                        pd.to_datetime(row.get("latest_official_sample_at")).to_pydatetime()
                        if pd.notna(row.get("latest_official_sample_at"))
                        else None
                    ),
                    geometry=Point(latitude=float(row["latitude"]), longitude=float(row["longitude"])),
                )
            )
        return beaches

    def get_beach(self, beach_id: str) -> BeachSummary:
        match = self.beaches_frame.loc[self.beaches_frame["beach_id"] == beach_id]
        if match.empty:
            raise HTTPException(status_code=404, detail=f"Unknown beach '{beach_id}'")
        row = match.iloc[0]
        return BeachSummary(
            id=row["beach_id"],
            name=_derive_friendly_name(row),
            county=row["county"],
            region=row["region"],
            support_status=row["support_status"],
            latest_official_sample_at=(
                pd.to_datetime(row.get("latest_official_sample_at")).to_pydatetime()
                if pd.notna(row.get("latest_official_sample_at"))
                else None
            ),
            geometry=Point(latitude=float(row["latitude"]), longitude=float(row["longitude"])),
        )

    def get_forecast(self, beach_id: str, forecast_date: date) -> ForecastRecord:
        if not self.forecasts_frame.empty:
            beach_forecasts = self.forecasts_frame.loc[
                self.forecasts_frame["beach_id"] == beach_id
            ]
            if not beach_forecasts.empty:
                forecast_dates = pd.to_datetime(beach_forecasts["forecast_date"]).dt.date
                exact = beach_forecasts.loc[forecast_dates == forecast_date]
                if not exact.empty:
                    return self._build_forecast_record(exact.iloc[0].to_dict(), beach_id)
                # No forecast for the requested date — return the most recent available.
                latest = beach_forecasts.loc[forecast_dates.idxmax()]
                return self._build_forecast_record(latest.to_dict(), beach_id)
        return self._derived_forecast(beach_id, forecast_date)

    def _build_forecast_record(self, row: dict, beach_id: str) -> ForecastRecord:
        env_fallback = self._latest_beach_day_env(beach_id)

        def pick(key: str) -> float | None:
            primary = _safe_float(row.get(key))
            return primary if primary is not None else env_fallback.get(key)

        environmental_summary = EnvironmentalSummary(
            wave_height_m=pick("wave_height_m"),
            dominant_period_s=pick("dominant_period_s"),
            water_temperature_c=pick("water_temperature_c"),
            salinity_psu=pick("salinity_psu"),
            uv_index=pick("uv_index"),
            wind_speed_mps=pick("wind_speed_mps"),
            wind_direction_deg=pick("wind_direction_deg"),
        )
        row["environmental_summary"] = environmental_summary
        return ForecastRecord.model_validate(row)

    def _latest_beach_day_env(self, beach_id: str) -> dict[str, float | None]:
        if self.beach_day_frame.empty:
            return {}
        rows = self.beach_day_frame.loc[self.beach_day_frame["beach_id"] == beach_id]
        if rows.empty:
            return {}
        latest = rows.sort_values("sample_date", ascending=False).iloc[0]
        return {
            key: _safe_float(latest.get(key))
            for key in (
                "wave_height_m",
                "dominant_period_s",
                "water_temperature_c",
                "salinity_psu",
                "uv_index",
                "wind_speed_mps",
                "wind_direction_deg",
            )
        }

    def _derived_forecast(self, beach_id: str, forecast_date: date) -> ForecastRecord:
        beach_obs = self.observations_frame.loc[self.observations_frame["beach_id"] == beach_id].copy()
        if beach_obs.empty:
            raise HTTPException(status_code=404, detail="Forecast data not available")
        beach_obs["sample_time"] = pd.to_datetime(beach_obs["sample_time"], errors="coerce")
        latest = beach_obs.sort_values("sample_time").iloc[-1]
        latest_value = float(latest["value"])
        ratio = max(latest_value / self.stv_threshold, 0.01)
        p_exceed = min(max(0.5 + 0.4 * (ratio - 1.0), 0.03), 0.97)
        predicted_log = log10(max(latest_value, 1.0))
        drivers = [
            "Latest official sample is above the marine threshold"
            if latest_value > self.stv_threshold
            else "Latest official sample remains below the marine threshold"
        ]
        if latest.get("weather"):
            drivers.append(f"Field notes recorded weather as {latest['weather']}")
        if latest.get("storm_drain_flow"):
            drivers.append(f"Storm drain flow noted as {latest['storm_drain_flow']}")

        return ForecastRecord(
            beach_id=beach_id,
            forecast_date=forecast_date,
            risk_band=risk_band(p_exceed),
            p_exceed=float(p_exceed),
            predicted_log_enterococcus=predicted_log,
            lower_prediction_interval=None,
            upper_prediction_interval=None,
            prediction_interval_level=None,
            top_drivers=drivers[:3],
            model_version="derived-persistence-v0",
            forecast_generated_at=datetime.now(UTC),
            environmental_summary=EnvironmentalSummary(),
        )

    def get_observations(self, beach_id: str) -> ObservationResponse:
        beach_obs = self.observations_frame.loc[self.observations_frame["beach_id"] == beach_id]
        if beach_obs.empty:
            raise HTTPException(status_code=404, detail="Observation history not available")

        observations = [
            ObservationRecord(
                sample_time=pd.to_datetime(row["sample_time"]).to_pydatetime(),
                analyte=row["analyte"],
                method=row["method"],
                units=row["units"],
                value=float(row["value"]),
                exceeds_stv=bool(row["exceeds_stv"]),
            )
            for _, row in beach_obs.sort_values("sample_time", ascending=False).head(25).iterrows()
        ]

        advisories = []
        beach_adv = self.advisories_frame.loc[self.advisories_frame["beach_id"] == beach_id]
        for _, row in beach_adv.sort_values("started_at", ascending=False).head(10).iterrows():
            advisories.append(
                AdvisoryRecord(
                    advisory_type=row["advisory_type"],
                    started_at=pd.to_datetime(row["started_at"]).to_pydatetime(),
                    ended_at=(
                        pd.to_datetime(row["ended_at"]).to_pydatetime()
                        if pd.notna(row.get("ended_at"))
                        else None
                    ),
                    status=row["status"],
                )
            )

        recent_environment = []
        beach_day = self.beach_day_frame.loc[self.beach_day_frame["beach_id"] == beach_id]
        if not beach_day.empty:
            for _, row in beach_day.sort_values("sample_date", ascending=False).head(10).iterrows():
                recent_environment.append(
                    {
                        "date": str(row["sample_date"]),
                        "wave_height_m": row.get("wave_height_m"),
                        "dominant_period_s": row.get("dominant_period_s"),
                        "water_temperature_c": row.get("water_temperature_c"),
                        "salinity_psu": row.get("salinity_psu"),
                        "weather": row.get("weather"),
                        "storm_drain_flow": row.get("storm_drain_flow"),
                        "tidal_height": row.get("tidal_height"),
                        "surf_height_observed": row.get("surf_height_observed"),
                        "turbidity_observed": row.get("turbidity_observed"),
                    }
                )

        return ObservationResponse(
            beach_id=beach_id,
            observations=observations,
            advisories=advisories,
            recent_environment=recent_environment,
        )

    def get_system_health(self) -> SystemHealthResponse:
        health_path = self.curated_dir / "system_health.json"
        payload = json.loads(health_path.read_text()) if health_path.exists() else {}
        return SystemHealthResponse.model_validate({"app_env": os.getenv("APP_ENV", "development"), **payload})
