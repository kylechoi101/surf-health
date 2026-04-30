from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import UTC, date, datetime
from math import isnan, log10
from pathlib import Path
from typing import Any

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
    ParentBeachSummary,
    Point,
    SystemHealthResponse,
)


def _safe_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        parsed = float(value)
        return None if isnan(parsed) else parsed
    except (TypeError, ValueError):
        return None


def _parse_json_list(value: object) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _parse_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed


def _parse_date(value: object) -> date:
    return date.fromisoformat(str(value)[:10])


def _derive_friendly_name(row: sqlite3.Row) -> str:
    beach_id = str(row["beach_id"])
    beach_id = re.sub(r"^ca\d+-", "", beach_id)
    county_slug = str(row["county"] or "").lower().replace(" ", "-")
    if beach_id.startswith(county_slug + "-"):
        beach_id = beach_id[len(county_slug) + 1 :]
    station_raw = str(row["name"] or "")
    station_slug = re.sub(r"[^a-z0-9]+", "-", station_raw.lower()).strip("-")
    if station_slug and beach_id.endswith("-" + station_slug):
        beach_id = beach_id[: -(len(station_slug) + 1)]
    return beach_id.replace("-", " ").title() if beach_id else station_raw


class ServingSnapshotRepository(BeachRepository):
    def __init__(self, snapshot_path: Path, stv_threshold: float) -> None:
        self.snapshot_path = Path(snapshot_path)
        self.stv_threshold = stv_threshold

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self.snapshot_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _fetch_one(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(query, params).fetchone()

    def _fetch_all(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return list(conn.execute(query, params).fetchall())

    def _forecast_model_lookup(self) -> dict[str, str]:
        rows = self._fetch_all("select beach_id, model_version from forecasts")
        return {str(row["beach_id"]): str(row["model_version"]) for row in rows}

    def _active_advisory_beach_ids(self) -> set[str]:
        rows = self._fetch_all("select distinct beach_id from advisories_recent where status = 'active'")
        return {str(row["beach_id"]) for row in rows}

    def _beach_from_row(self, row: sqlite3.Row, model_version: str | None = None) -> BeachSummary:
        support = str(row["support_status"]) if model_version else "unsupported"
        return BeachSummary(
            id=str(row["beach_id"]),
            name=_derive_friendly_name(row),
            county=str(row["county"]),
            region=str(row["region"]),
            support_status=support,
            model_version=model_version,
            latest_official_sample_at=_parse_datetime(row["latest_official_sample_at"]),
            geometry=Point(
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
            ),
        )

    def list_parent_beaches(self) -> list[ParentBeachSummary]:
        rows = self._fetch_all("select * from parent_beaches")
        if not rows:
            return []

        forecasts = self._fetch_all("select beach_id, risk_band, p_exceed, model_version from forecasts")
        forecast_lookup = {
            str(row["beach_id"]): (
                str(row["risk_band"]),
                float(row["p_exceed"]),
                str(row["model_version"]),
            )
            for row in forecasts
        }
        active_beach_ids = self._active_advisory_beach_ids()

        parents: list[ParentBeachSummary] = []
        for row in rows:
            member_ids = [str(member_id) for member_id in _parse_json_list(row["member_beach_ids"])]
            member_forecasts = [
                forecast_lookup[beach_id] for beach_id in member_ids if beach_id in forecast_lookup
            ]
            worst_band: str | None = None
            worst_p: float | None = None
            worst_model_v: str | None = None
            if member_forecasts:
                worst_band, worst_p, worst_model_v = max(member_forecasts, key=lambda item: item[1])

            parents.append(
                ParentBeachSummary(
                    id=str(row["parent_beach_id"]),
                    name=str(row["name"]),
                    county=str(row["county"]),
                    region=str(row["region"]),
                    support_status=str(row["support_status"]) if worst_model_v else "unsupported",
                    model_version=worst_model_v,
                    station_count=int(row["station_count"]),
                    member_beach_ids=member_ids,
                    latest_official_sample_at=_parse_datetime(row["latest_official_sample_at"]),
                    geometry=Point(
                        latitude=float(row["latitude"]),
                        longitude=float(row["longitude"]),
                    ),
                    risk_band=worst_band,
                    p_exceed=worst_p,
                    has_active_advisory=any(beach_id in active_beach_ids for beach_id in member_ids),
                )
            )
        return parents

    def list_beaches(self) -> list[BeachSummary]:
        forecast_models = self._forecast_model_lookup()
        return [
            self._beach_from_row(row, forecast_models.get(str(row["beach_id"])))
            for row in self._fetch_all("select * from beaches")
        ]

    def get_beach(self, beach_id: str) -> BeachSummary:
        row = self._fetch_one("select * from beaches where beach_id = ?", (beach_id,))
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown beach '{beach_id}'")
        return self._beach_from_row(row, self._forecast_model_lookup().get(beach_id))

    def get_forecast(self, beach_id: str, forecast_date: date) -> ForecastRecord:
        row = self._fetch_one(
            "select * from forecasts where beach_id = ? and forecast_date = ?",
            (beach_id, forecast_date.isoformat()),
        )
        if row is None:
            row = self._fetch_one(
                "select * from forecasts where beach_id = ? order by forecast_date desc limit 1",
                (beach_id,),
            )
        if row is not None:
            return self._build_forecast_record(dict(row), beach_id)
        return self._derived_forecast(beach_id, forecast_date)

    def _build_forecast_record(self, row: dict[str, object], beach_id: str) -> ForecastRecord:
        env_fallback = self._latest_env(beach_id)

        def pick(key: str) -> float | None:
            primary = _safe_float(row.get(key))
            return primary if primary is not None else env_fallback.get(key)

        gen_at = _parse_datetime(row.get("forecast_generated_at"))
        age_hours = None
        if gen_at is not None:
            now_utc = datetime.now(UTC)
            if gen_at.tzinfo is None:
                gen_at = gen_at.replace(tzinfo=UTC)
            age_hours = max(0, int((now_utc - gen_at).total_seconds() / 3600))

        return ForecastRecord(
            beach_id=beach_id,
            forecast_date=_parse_date(row.get("forecast_date")),
            risk_band=str(row["risk_band"]),
            p_exceed=float(row["p_exceed"]),
            predicted_log_enterococcus=_safe_float(row.get("predicted_log_enterococcus")),
            lower_prediction_interval=_safe_float(row.get("lower_prediction_interval")),
            upper_prediction_interval=_safe_float(row.get("upper_prediction_interval")),
            prediction_interval_level=_safe_float(row.get("prediction_interval_level")),
            top_drivers=[str(item) for item in _parse_json_list(row.get("top_drivers"))],
            model_version=str(row["model_version"]),
            forecast_generated_at=gen_at or datetime.now(UTC),
            forecast_age_hours=age_hours,
            environmental_summary=EnvironmentalSummary(
                wave_height_m=pick("wave_height_m"),
                dominant_period_s=pick("dominant_period_s"),
                water_temperature_c=pick("water_temperature_c"),
                salinity_psu=pick("salinity_psu"),
                uv_index=pick("uv_index"),
                wind_speed_mps=pick("wind_speed_mps"),
                wind_direction_deg=pick("wind_direction_deg"),
            ),
        )

    def _latest_env(self, beach_id: str) -> dict[str, float | None]:
        row = self._fetch_one("select * from latest_env where beach_id = ?", (beach_id,))
        if row is None:
            return {}
        return {
            key: _safe_float(row[key])
            for key in (
                "wave_height_m",
                "dominant_period_s",
                "water_temperature_c",
                "salinity_psu",
                "uv_index",
                "wind_speed_mps",
                "wind_direction_deg",
            )
            if key in row.keys()
        }

    def _derived_forecast(self, beach_id: str, forecast_date: date) -> ForecastRecord:
        latest = self._fetch_one(
            "select * from observations_recent where beach_id = ? order by sample_time desc limit 1",
            (beach_id,),
        )
        if latest is None:
            raise HTTPException(status_code=404, detail="Forecast data not available")
        latest_value = float(latest["value"])
        ratio = max(latest_value / self.stv_threshold, 0.01)
        p_exceed = min(max(0.5 + 0.4 * (ratio - 1.0), 0.03), 0.97)
        drivers = [
            "Latest official sample is above the marine threshold"
            if latest_value > self.stv_threshold
            else "Latest official sample remains below the marine threshold"
        ]
        for key, label in (("weather", "weather"), ("storm_drain_flow", "storm drain flow")):
            value = latest[key] if key in latest.keys() else None
            if value and str(value).lower() not in ("nan", "none", ""):
                drivers.append(f"Field notes recorded {label} as {value}")

        return ForecastRecord(
            beach_id=beach_id,
            forecast_date=forecast_date,
            risk_band=risk_band(p_exceed),
            p_exceed=float(p_exceed),
            predicted_log_enterococcus=log10(max(latest_value, 1.0)),
            model_version="derived-persistence-v0",
            forecast_generated_at=datetime.now(UTC),
            environmental_summary=EnvironmentalSummary(),
            top_drivers=drivers[:3],
        )

    def get_observations(self, beach_id: str) -> ObservationResponse:
        rows = self._fetch_all(
            "select * from observations_recent where beach_id = ? "
            "order by sample_time desc limit 25",
            (beach_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Observation history not available")

        observations = [
            ObservationRecord(
                sample_time=_parse_datetime(row["sample_time"]) or datetime.now(UTC),
                analyte=str(row["analyte"]),
                method=str(row["method"]),
                units=str(row["units"]),
                value=float(row["value"]),
                exceeds_stv=bool(row["exceeds_stv"]),
            )
            for row in rows
        ]

        advisories = [
            AdvisoryRecord(
                advisory_type=str(row["advisory_type"]),
                started_at=_parse_datetime(row["started_at"]) or datetime.now(UTC),
                ended_at=_parse_datetime(row["ended_at"]),
                status=str(row["status"]),
            )
            for row in self._fetch_all(
                "select * from advisories_recent where beach_id = ? "
                "order by started_at desc limit 10",
                (beach_id,),
            )
        ]

        recent_environment = [
            {
                "date": str(row["sample_date"])[:10],
                "wave_height_m": _safe_float(row["wave_height_m"]),
                "dominant_period_s": _safe_float(row["dominant_period_s"]),
                "water_temperature_c": _safe_float(row["water_temperature_c"]),
                "salinity_psu": _safe_float(row["salinity_psu"]),
                "weather": row["weather"],
                "storm_drain_flow": row["storm_drain_flow"],
                "tidal_height": _safe_float(row["tidal_height"]),
                "surf_height_observed": _safe_float(row["surf_height_observed"]),
                "turbidity_observed": _safe_float(row["turbidity_observed"]),
            }
            for row in self._fetch_all(
                "select * from recent_environment where beach_id = ? "
                "order by sample_date desc limit 10",
                (beach_id,),
            )
        ]

        return ObservationResponse(
            beach_id=beach_id,
            observations=observations,
            advisories=advisories,
            recent_environment=recent_environment,
        )

    def get_system_health(self) -> SystemHealthResponse:
        row = self._fetch_one("select payload from system_health where key = 'health'")
        payload = json.loads(row["payload"]) if row is not None else {}
        active_count = self._fetch_one(
            "select count(*) as count from advisories_recent where status = 'active'"
        )

        audit = None
        audit_row = self._fetch_one("select payload from system_health where key = 'advisory_audit'")
        if audit_row is not None:
            try:
                raw = json.loads(audit_row["payload"])
                audit = {
                    "generated_at": raw.get("generated_at"),
                    "agreement_rate": raw.get("agreement_rate"),
                    "false_negatives": raw.get("false_negatives", {}).get("count"),
                    "false_positives": raw.get("false_positives", {}).get("count"),
                    "active_advisories": raw.get("active_advisories"),
                }
            except json.JSONDecodeError:
                audit = None

        return SystemHealthResponse.model_validate(
            {
                "app_env": os.getenv("APP_ENV", "development"),
                "active_advisories_count": int(active_count["count"]) if active_count else 0,
                "forecast_audit": audit,
                **payload,
            }
        )
