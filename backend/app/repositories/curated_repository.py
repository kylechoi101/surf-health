from __future__ import annotations

import ast
import json
import os
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from functools import cached_property
from math import log10
from pathlib import Path
from threading import RLock

import pandas as pd
import pyarrow.parquet as pq
from fastapi import HTTPException

from app.ml.calibration import risk_band
from app.repositories.base import BeachRepository
from app.services.shore_normal import compute_shore_normal_deg
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
    sample_recency_band,
)

# Advisories from data.ca.gov sometimes carry status="active" for years because
# the county never logged a closure event. A bacterial-violation advisory in
# real life rarely lasts more than a week; treating a 4-year-old "active" row
# as currently in effect produces false positives like Windansea (advisory
# posted 2022-07-12, never closed). 14 days matches WHO/EPA acute-event
# guidance and the audit script's acute-pool boundary — any advisory not
# re-posted in two weeks is bureaucratic, not operational.
ADVISORY_MAX_AGE_DAYS = 14


def filter_currently_active(advisories: pd.DataFrame) -> pd.DataFrame:
    """Return the rows that are both status='active' and currently in effect.

    Postings (and similar acute advisories) are gated by the
    ADVISORY_MAX_AGE_DAYS window to prevent zombie records (counties
    don't reliably log closure events).

    Closures are NOT age-gated — they describe ongoing health hazards that
    persist until the county explicitly lifts them. Long-standing shoreline
    closures (Tijuana Slough since Oct 2025, Imperial Beach Pier since
    Dec 2025) need to surface forever until the scraper stops seeing them
    in the live feed (at which point the county-direct merge demotes
    them via the authoritative-county rule).
    """
    if advisories.empty or "status" not in advisories.columns:
        return advisories.iloc[0:0]
    active = advisories.loc[advisories["status"] == "active"].copy()
    if active.empty:
        return active
    if "started_at" not in active.columns:
        return active
    started = pd.to_datetime(active["started_at"], errors="coerce", utc=True)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=ADVISORY_MAX_AGE_DAYS)
    advisory_type = active.get("advisory_type", pd.Series("", index=active.index))
    is_closure = advisory_type.fillna("").str.contains("closure", case=False, na=False)
    return active.loc[is_closure | (started >= cutoff)]


OBSERVATION_COLUMNS = [
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
]

BEACH_DAY_RECENT_COLUMNS = [
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
]

OFFICIAL_ADVISORY_DRIVER = "Official health advisory is active for this station."


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


def _safe_int(value: object) -> int | None:
    number = _safe_float(value)
    return int(number) if number is not None else None


def _coerce_advisory_website(raw: object) -> str | None:
    if raw is None:
        return None
    try:
        if pd.isna(raw):
            return None
    except (TypeError, ValueError):
        pass
    text = str(raw).strip()
    if not text or text.lower() == "unknown":
        return None
    return text


def _safe_bool(value: object, *, default: bool = True) -> bool:
    """Parse a boolean that may have been stored as string/int in parquet/SQLite."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        return value.lower() not in ("0", "false", "no", "")
    return default


def _driver_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return [value]
        if isinstance(parsed, (list, tuple)):
            return [str(item) for item in parsed]
        return [value]
    if isinstance(value, Iterable) and not isinstance(value, (bytes, dict)):
        return [str(item) for item in value]
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    return [str(value)]


def _read_filtered_parquet(path: Path, beach_id: str, columns: list[str]) -> pd.DataFrame:
    try:
        available_columns = set(pq.ParquetFile(path).schema.names)
        read_columns = [column for column in columns if column in available_columns]
    except Exception:
        read_columns = columns

    frame = pq.read_table(
        path,
        columns=read_columns,
        filters=[("beach_id", "==", beach_id)],
    ).to_pandas()
    for column in columns:
        if column not in frame.columns:
            frame[column] = None
    return frame[columns]


class CuratedBeachRepository(BeachRepository):
    def __init__(self, curated_dir: Path, stv_threshold: float) -> None:
        self.curated_dir = curated_dir
        self.stv_threshold = stv_threshold
        self._per_beach_read_lock = RLock()
        self._obs_cache: dict[str, pd.DataFrame] = {}
        self._beach_day_cache: dict[str, pd.DataFrame] = {}

    def _cached_filtered_parquet(
        self,
        cache: dict[str, pd.DataFrame],
        path: Path,
        beach_id: str,
        columns: list[str],
    ) -> pd.DataFrame:
        cached = cache.get(beach_id)
        if cached is not None:
            return cached

        with self._per_beach_read_lock:
            cached = cache.get(beach_id)
            if cached is not None:
                return cached

            frame = _read_filtered_parquet(path, beach_id, columns)
            cache[beach_id] = frame
            return frame

    @cached_property
    def beaches_frame(self) -> pd.DataFrame:
        return pd.read_parquet(self.curated_dir / "beaches.parquet")

    @cached_property
    def advisories_frame(self) -> pd.DataFrame:
        path = self.curated_dir / "advisories.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    @cached_property
    def latest_env_frame(self) -> pd.DataFrame:
        # One row per beach — written by training._export_forecasts (tiny, ~50 KB).
        # Replaces the old beach_day_frame cached_property on the API path.
        path = self.curated_dir / "latest_env.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    def _obs_for_beach(self, beach_id: str) -> pd.DataFrame:
        path = self.curated_dir / "observations.parquet"
        if not path.exists():
            return pd.DataFrame()
        return self._cached_filtered_parquet(
            self._obs_cache,
            path,
            beach_id,
            OBSERVATION_COLUMNS,
        )

    def _beach_day_for_beach(self, beach_id: str) -> pd.DataFrame:
        path = self.curated_dir / "beach_day.parquet"
        if not path.exists():
            return pd.DataFrame()
        return self._cached_filtered_parquet(
            self._beach_day_cache,
            path,
            beach_id,
            BEACH_DAY_RECENT_COLUMNS,
        )

    @cached_property
    def forecasts_frame(self) -> pd.DataFrame:
        path = self.curated_dir / "forecasts.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    @cached_property
    def parent_beaches_frame(self) -> pd.DataFrame:
        path = self.curated_dir / "parent_beaches.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    def list_parent_beaches(self) -> list[ParentBeachSummary]:
        if self.parent_beaches_frame.empty:
            return []

        # Build forecast lookup: worst-case p_exceed per member station
        forecast_lookup: dict[str, tuple[str, float, str]] = {}
        if not self.forecasts_frame.empty:
            for _, row in self.forecasts_frame.iterrows():
                bid = row["beach_id"]
                forecast_lookup[bid] = (str(row["risk_band"]), float(row["p_exceed"]), str(row.get("model_version", "unknown")))

        # Build advisory lookup: any active advisory per station, plus URL from most-recent active
        active_stations: set[str] = set()
        advisory_website_lookup: dict[str, str | None] = {}
        if not self.advisories_frame.empty:
            active = filter_currently_active(self.advisories_frame)
            active_stations = set(active["beach_id"].tolist())
            if "advisory_website" in active.columns and not active.empty:
                # Most-recent active advisory URL per station
                for bid, grp in active.groupby("beach_id"):
                    sorted_grp = grp.sort_values("started_at", ascending=False)
                    advisory_website_lookup[str(bid)] = _coerce_advisory_website(
                        sorted_grp.iloc[0].get("advisory_website")
                    )

        parents: list[ParentBeachSummary] = []
        for _, row in self.parent_beaches_frame.iterrows():
            member_ids: list[str] = list(row["member_beach_ids"])
            member_forecasts = [forecast_lookup[bid] for bid in member_ids if bid in forecast_lookup]
            worst_band: str | None = None
            worst_p: float | None = None
            worst_model_v: str | None = None
            if member_forecasts:
                worst = max(member_forecasts, key=lambda x: x[1])
                worst_band, worst_p, worst_model_v = worst

            lat = _safe_float(row.get("latitude"))
            lon = _safe_float(row.get("longitude"))
            if lat is None or lon is None:
                continue
            
            support = row.get("support_status", "unsupported") if worst_model_v else "unsupported"

            has_active = any(bid in active_stations for bid in member_ids)
            # Pick advisory website from first active member station that has one
            advisory_website: str | None = None
            if has_active:
                for bid in member_ids:
                    url = advisory_website_lookup.get(bid)
                    if url:
                        advisory_website = url
                        break

            parents.append(ParentBeachSummary(
                id=str(row["parent_beach_id"]),
                name=str(row["name"]),
                county=str(row["county"]),
                region=str(row["region"]),
                support_status=support,
                model_version=worst_model_v,
                station_count=int(row["station_count"]),
                member_beach_ids=member_ids,
                latest_official_sample_at=(
                    pd.to_datetime(row.get("latest_official_sample_at")).to_pydatetime()
                    if pd.notna(row.get("latest_official_sample_at"))
                    else None
                ),
                geometry=Point(latitude=lat, longitude=lon),
                risk_band=worst_band,
                p_exceed=worst_p,
                has_active_advisory=has_active,
                advisory_website=advisory_website,
            ))
        return parents

    def _beach_geometry_population(self) -> list[tuple[str, float, float]]:
        """Flat list of (beach_id, lat, lon) for the shore-normal SVD search."""
        if self.beaches_frame.empty:
            return []
        rows: list[tuple[str, float, float]] = []
        for _, row in self.beaches_frame.iterrows():
            lat = row.get("latitude")
            lon = row.get("longitude")
            if pd.isna(lat) or pd.isna(lon):
                continue
            rows.append((str(row["beach_id"]), float(lat), float(lon)))
        return rows

    def list_beaches(self) -> list[BeachSummary]:
        forecast_models: dict[str, str] = {}
        if not self.forecasts_frame.empty:
            for _, row in self.forecasts_frame.iterrows():
                forecast_models[row["beach_id"]] = str(row.get("model_version", "unknown"))

        population = self._beach_geometry_population()
        beaches: list[BeachSummary] = []
        for _, row in self.beaches_frame.iterrows():
            bid = row["beach_id"]
            model_v = forecast_models.get(bid)
            support = row["support_status"] if model_v else "unsupported"
            beaches.append(
                BeachSummary(
                    id=bid,
                    name=_derive_friendly_name(row),
                    county=row["county"],
                    region=row["region"],
                    support_status=support,
                    model_version=model_v,
                    latest_official_sample_at=(
                        pd.to_datetime(row.get("latest_official_sample_at")).to_pydatetime()
                        if pd.notna(row.get("latest_official_sample_at"))
                        else None
                    ),
                    geometry=Point(latitude=float(row["latitude"]), longitude=float(row["longitude"])),
                    shore_normal_deg=compute_shore_normal_deg(str(bid), population),
                )
            )
        return beaches

    def get_beach(self, beach_id: str) -> BeachSummary:
        match = self.beaches_frame.loc[self.beaches_frame["beach_id"] == beach_id]
        if match.empty:
            raise HTTPException(status_code=404, detail=f"Unknown beach '{beach_id}'")
        row = match.iloc[0]

        model_v = None
        if not self.forecasts_frame.empty:
            f_match = self.forecasts_frame.loc[self.forecasts_frame["beach_id"] == beach_id]
            if not f_match.empty:
                model_v = str(f_match.iloc[0].get("model_version", "unknown"))

        support = row["support_status"] if model_v else "unsupported"

        return BeachSummary(
            id=row["beach_id"],
            name=_derive_friendly_name(row),
            county=row["county"],
            region=row["region"],
            support_status=support,
            model_version=model_v,
            latest_official_sample_at=(
                pd.to_datetime(row.get("latest_official_sample_at")).to_pydatetime()
                if pd.notna(row.get("latest_official_sample_at"))
                else None
            ),
            geometry=Point(latitude=float(row["latitude"]), longitude=float(row["longitude"])),
            shore_normal_deg=compute_shore_normal_deg(
                str(row["beach_id"]),
                self._beach_geometry_population(),
            ),
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
        active_advisory = self._has_active_advisory(beach_id)
        raw_p_exceed = _safe_float(row.get("p_exceed_raw"))
        model_risk_band = risk_band(raw_p_exceed) if raw_p_exceed is not None else str(row["risk_band"])

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
        
        try:
            gen_at = pd.to_datetime(row.get("forecast_generated_at"))
            now_utc = pd.Timestamp.now(tz="UTC")
            if gen_at.tz is None:
                gen_at = gen_at.tz_localize("UTC")
            age_hours = int((now_utc - gen_at).total_seconds() / 3600)
            row["forecast_age_hours"] = max(0, age_hours)
        except Exception:
            row["forecast_age_hours"] = None

        if active_advisory:
            row["official_advisory_active"] = True
            row["model_risk_band"] = model_risk_band
            row["risk_band"] = "Advisory"
            row["forecast_label_mode"] = "official_advisory_override"
            row["top_drivers"] = self._advisory_override_drivers(row.get("top_drivers"))
            row["advisory_website"] = self._active_advisory_website(beach_id)

        sample_age = _safe_int(row.get("sample_age_days"))
        if sample_age is None:
            sample_age = self._sample_age_days(beach_id, row.get("forecast_date"))
        row["sample_age_days"] = sample_age
        row["sample_recency_band"] = str(row.get("sample_recency_band") or sample_recency_band(sample_age))
        row["is_beta_forecast"] = _safe_bool(row.get("is_beta_forecast"), default=True)

        return ForecastRecord.model_validate(row)

    def _latest_beach_day_env(self, beach_id: str) -> dict[str, float | None]:
        if self.latest_env_frame.empty:
            return {}
        rows = self.latest_env_frame.loc[self.latest_env_frame["beach_id"] == beach_id]
        if rows.empty:
            return {}
        latest = rows.iloc[0]
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

    def _active_advisory_beach_ids(self) -> set[str]:
        active = filter_currently_active(self.advisories_frame)
        if active.empty:
            return set()
        return {str(beach_id) for beach_id in active["beach_id"].dropna()}

    def _has_active_advisory(self, beach_id: str) -> bool:
        return beach_id in self._active_advisory_beach_ids()

    def _active_advisory_website(self, beach_id: str) -> str | None:
        active = filter_currently_active(self.advisories_frame)
        if active.empty or "advisory_website" not in active.columns:
            return None
        rows = active.loc[active["beach_id"] == beach_id]
        rows = rows.loc[rows["advisory_website"].notna()]
        if rows.empty:
            return None
        rows = rows.sort_values("started_at", ascending=False)
        return _coerce_advisory_website(rows.iloc[0].get("advisory_website"))

    def _advisory_override_drivers(self, drivers: object) -> list[str]:
        base_drivers = [
            driver for driver in _driver_list(drivers) if driver != OFFICIAL_ADVISORY_DRIVER
        ]
        return [OFFICIAL_ADVISORY_DRIVER, *base_drivers][:5]

    def _derived_forecast(self, beach_id: str, forecast_date: date) -> ForecastRecord:
        beach_obs = self._obs_for_beach(beach_id).copy()
        if beach_obs.empty:
            raise HTTPException(status_code=404, detail="Forecast data not available")
        beach_obs["sample_time"] = pd.to_datetime(beach_obs["sample_time"], errors="coerce")
        latest = beach_obs.sort_values("sample_time").iloc[-1]
        sample_age = self._sample_age_days_from_value(latest["sample_time"], forecast_date)
        recency_band = sample_recency_band(sample_age)
        if recency_band in ("stale", "very_stale"):
            raise HTTPException(
                status_code=404,
                detail="Forecast data not available because the latest sample is not fresh.",
            )
        latest_value = float(latest["value"])
        ratio = max(latest_value / self.stv_threshold, 0.01)
        p_exceed = min(max(0.5 + 0.4 * (ratio - 1.0), 0.03), 0.97)
        predicted_log = log10(max(latest_value, 1.0))
        drivers = [
            "Latest official sample is above the marine threshold"
            if latest_value > self.stv_threshold
            else "Latest official sample remains below the marine threshold"
        ]
        weather = latest.get("weather")
        if weather and str(weather).lower() not in ("nan", "none", ""):
            drivers.append(f"Field notes recorded weather as {weather}")
        storm = latest.get("storm_drain_flow")
        if storm and str(storm).lower() not in ("nan", "none", ""):
            drivers.append(f"Storm drain flow noted as {storm}")
        model_risk_band = risk_band(p_exceed)
        active_advisory = self._has_active_advisory(beach_id)
        if active_advisory:
            drivers = self._advisory_override_drivers(drivers)

        return ForecastRecord(
            beach_id=beach_id,
            forecast_date=forecast_date,
            risk_band="Advisory" if active_advisory else model_risk_band,
            model_risk_band=model_risk_band if active_advisory else None,
            p_exceed=float(p_exceed),
            p_exceed_raw=float(p_exceed),
            advisory_floor_applied=False,
            predicted_log_enterococcus=predicted_log,
            lower_prediction_interval=None,
            upper_prediction_interval=None,
            prediction_interval_level=None,
            top_drivers=drivers[:3],
            model_version="derived-persistence-v0",
            forecast_generated_at=datetime.now(UTC),
            official_advisory_active=active_advisory,
            forecast_label_mode=(
                "official_advisory_override" if active_advisory else "derived_persistence"
            ),
            sample_age_days=sample_age,
            sample_recency_band=recency_band,
            is_beta_forecast=True,
            environmental_summary=EnvironmentalSummary(),
        )

    def _sample_age_days(self, beach_id: str, forecast_date_value: object) -> int | None:
        if not (self.curated_dir / "beaches.parquet").exists() or self.beaches_frame.empty:
            return None
        rows = self.beaches_frame.loc[self.beaches_frame["beach_id"] == beach_id]
        if rows.empty:
            return None
        return self._sample_age_days_from_value(
            rows.iloc[0].get("latest_official_sample_at"),
            forecast_date_value,
        )

    def _sample_age_days_from_value(self, sample_time: object, forecast_date_value: object) -> int | None:
        sample_ts = pd.to_datetime(sample_time, errors="coerce")
        forecast_ts = pd.to_datetime(forecast_date_value, errors="coerce")
        if pd.isna(sample_ts) or pd.isna(forecast_ts):
            return None
        return max(0, int((forecast_ts.date() - sample_ts.date()).days))

    def get_observations(self, beach_id: str) -> ObservationResponse:
        beach_obs = self._obs_for_beach(beach_id)
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
                    advisory_website=_coerce_advisory_website(row.get("advisory_website")),
                )
            )

        recent_environment = []
        beach_day = self._beach_day_for_beach(beach_id)
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
                        # Wind + UV daily aggregates from solar_wind pipeline.
                        "wind_speed_mps": row.get("wind_speed_24h_max"),
                        "wind_direction_deg": row.get("wind_direction_24h_mean"),
                        "uv_index": row.get("uv_index_24h_max"),
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

        active_count = 0
        if not self.advisories_frame.empty:
            active_count = int((self.advisories_frame["status"] == "active").sum())

        audit: dict | None = None
        audit_path = self.curated_dir / "advisory_audit.json"
        if audit_path.exists():
            try:
                raw = json.loads(audit_path.read_text())
                audit = {
                    "generated_at": raw.get("generated_at"),
                    "agreement_rate": raw.get("agreement_rate"),
                    "false_negatives": raw.get("false_negatives", {}).get("count"),
                    "false_positives": raw.get("false_positives", {}).get("count"),
                    "active_advisories": raw.get("active_advisories"),
                }
            except Exception:
                pass

        return SystemHealthResponse.model_validate({
            "app_env": os.getenv("APP_ENV", "development"),
            "is_beta_product": True,
            "active_advisories_count": active_count,
            "forecast_audit": audit,
            "repository_mode": "parquet",
            **payload
        })
