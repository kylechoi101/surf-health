from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import UTC, date, datetime
from functools import cache
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
    sample_recency_band,
)


def _coerce_advisory_website(raw: object) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, float) and isnan(raw):
        return None
    text = str(raw).strip()
    if not text or text.lower() == "unknown":
        return None
    return text


def _safe_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        parsed = float(value)
        return None if isnan(parsed) else parsed
    except (TypeError, ValueError):
        return None


def _row_get(row: object, key: str) -> object | None:
    """Tolerant sqlite3.Row accessor — returns None for keys not in the cursor
    schema. Lets us read columns that may or may not exist depending on when
    the sqlite snapshot was last baked."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _safe_int(value: object) -> int | None:
    number = _safe_float(value)
    return int(number) if number is not None else None


def _safe_bool(value: object, *, default: bool = True) -> bool:
    """Parse a boolean that may have been stored as string/int in SQLite."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        return value.lower() not in ("0", "false", "no", "")
    return default


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
    b_name = str(row["beach_name"]) if "beach_name" in row.keys() and row["beach_name"] else ""
    # If we have an explicit beach name (as opposed to a station name), keep it stable.
    # Downstream products can separately surface the station name if needed, but the
    # canonical beach name should not change when station metadata changes.
    if b_name:
        return b_name

    if not b_name:
        beach_id = str(row["beach_id"])
        beach_id = re.sub(r"^ca\d+-", "", beach_id)
        county_slug = str(row["county"] or "").lower().replace(" ", "-")
        if beach_id.startswith(county_slug + "-"):
            beach_id = beach_id[len(county_slug) + 1 :]
        station_raw = str(row["name"] or "")
        station_slug = re.sub(r"[^a-z0-9]+", "-", station_raw.lower()).strip("-")
        if station_slug and beach_id.endswith("-" + station_slug):
            beach_id = beach_id[: -(len(station_slug) + 1)]
        b_name = beach_id.replace("-", " ").title() if beach_id else station_raw

    s_name = str(row["name"] or "")
    
    if b_name and s_name and b_name.lower() != s_name.lower() and s_name.lower() not in b_name.lower():
        return f"{b_name} ({s_name})"
    return b_name or s_name


class ServingSnapshotRepository(BeachRepository):
    def __init__(self, snapshot_path: Path, stv_threshold: float) -> None:
        self.snapshot_path = Path(snapshot_path)
        self.stv_threshold = stv_threshold
        self._parent_name_by_member_id: dict[str, str] | None = None

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

    def _parent_name_lookup(self) -> dict[str, str]:
        if self._parent_name_by_member_id is not None:
            return self._parent_name_by_member_id
        mapping: dict[str, str] = {}
        rows = self._fetch_all("select parent_beach_id, name, member_beach_ids from parent_beaches")
        for row in rows:
            parent_name = str(row["name"] or "").strip()
            if not parent_name:
                continue
            for member_id in _parse_json_list(row["member_beach_ids"]):
                member_key = str(member_id)
                if member_key and member_key not in mapping:
                    mapping[member_key] = parent_name
        self._parent_name_by_member_id = mapping
        return mapping

    # data.ca.gov advisories are sometimes left status='active' for years after
    # the actual posting was lifted (counties don't reliably log closure events).
    # Only treat an advisory as currently in effect if its start date is within
    # this window. 14 days matches WHO/EPA acute-event guidance and the audit
    # script's acute-pool boundary — any advisory not re-posted in two weeks
    # is bureaucratic, not operational.
    _ACTIVE_ADVISORY_WINDOW_DAYS = 14

    # Closure-class advisories (e.g. the chronic Tijuana Slough closure
    # active since 2025-10-13) describe ongoing hazards that the county
    # never explicitly lifts, so they bypass the 14-day acute window and
    # remain visible until the source feed stops listing them. Postings
    # still get the 14-day gate. Mirrors `bake_web_static._active_advisory_set`
    # so the web's baked JSON and the API agree.
    _CLOSURE_EXEMPT_FILTER = (
        "(lower(coalesce(advisory_type, '')) like '%closure%' "
        f"or started_at >= datetime('now', '-{_ACTIVE_ADVISORY_WINDOW_DAYS} days'))"
    )

    def _active_advisory_beach_ids(self) -> set[str]:
        rows = self._fetch_all(
            "select distinct beach_id from advisories_recent "
            "where status = 'active' "
            f"and {self._CLOSURE_EXEMPT_FILTER}"
        )
        return {str(row["beach_id"]) for row in rows}

    def _active_advisory_websites(self) -> dict[str, str | None]:
        """Return the most-recent active advisory URL per beach_id."""
        rows = self._fetch_all(
            "select beach_id, advisory_website from advisories_recent "
            "where status = 'active' "
            f"and {self._CLOSURE_EXEMPT_FILTER} "
            "order by started_at desc"
        )
        result: dict[str, str | None] = {}
        for row in rows:
            bid = str(row["beach_id"])
            if bid not in result:
                result[bid] = _coerce_advisory_website(row["advisory_website"] if "advisory_website" in row.keys() else None)
        return result

    @cache
    def _station_to_parent_members(self) -> dict[str, tuple[str, ...]]:
        """For each station beach_id, return the list of sibling station ids
        that share the same parent (via the parent_beaches table's
        member_beach_ids). Used by the per-station forecast to flag when a
        sibling is under an active advisory.
        """
        result: dict[str, tuple[str, ...]] = {}
        try:
            rows = self._fetch_all(
                "select parent_beach_id, member_beach_ids from parent_beaches"
            )
        except sqlite3.OperationalError:
            return result
        for row in rows:
            raw = row["member_beach_ids"] if "member_beach_ids" in row.keys() else None
            try:
                members = tuple(str(b) for b in json.loads(raw)) if raw else tuple()
            except (TypeError, ValueError, json.JSONDecodeError):
                # Sometimes stored as a python-list-stringified column; fall back to string parsing.
                if isinstance(raw, str):
                    members = tuple(s.strip().strip("'\"") for s in raw.strip("[]").split(",") if s.strip())
                else:
                    members = tuple()
            for bid in members:
                result[bid] = members
        return result

    def _parent_advisory_signal(self, beach_id: str, active_set: set[str], website_map: dict[str, str | None]) -> tuple[bool, str | None]:
        """Return (parent_has_active_advisory, parent_advisory_website) for
        a station that does NOT have its own active advisory. Looks at
        every sibling under the same parent; if any sibling is under an
        active advisory, return True + that sibling's URL (so the UI can
        link to the same county source the parent card uses)."""
        siblings = self._station_to_parent_members().get(beach_id, ())
        if not siblings:
            return False, None
        for sibling_id in siblings:
            if sibling_id == beach_id:
                continue
            if sibling_id in active_set:
                return True, website_map.get(sibling_id)
        return False, None

    def _beach_from_row(self, row: sqlite3.Row, model_version: str | None = None) -> BeachSummary:
        # Trust the curated `support_status` as the source of truth for whether
        # the model covers this beach. A missing daily forecast does NOT mean
        # the beach is unsupported — it may just be a same-day data gap. The
        # apps surface "no current forecast" separately from "no model
        # coverage at all".
        curated_support = str(row["support_status"]) if row["support_status"] else "unsupported"
        if curated_support == "unsupported":
            support = "unsupported"
        elif model_version:
            support = curated_support
        else:
            support = curated_support  # production/beta beach with a same-day forecast gap
        beach_id = str(row["beach_id"])
        parent_name = self._parent_name_lookup().get(beach_id)
        station_nickname_raw = str(row["name"] or "").strip()
        # Some upstream rows arrive with literally-escaped apostrophes
        # (e.g. "Black\\'s Beach") because the source CSV/JSON was double-
        # escaped. Strip the spurious backslashes for display.
        station_nickname = station_nickname_raw.replace("\\'", "'").replace("\\\\", "") or None
        friendly = _derive_friendly_name(row)
        return BeachSummary(
            id=beach_id,
            name=parent_name or friendly,
            station_name=station_nickname,
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
        advisory_websites = self._active_advisory_websites()
        # member_id -> local nickname (e.g. "Black's Beach"), so the apps can
        # match search queries against the actual names users know stations by.
        # Some upstream rows ship with double-escaped apostrophes; clean them
        # for display so the apps don't render backslashes in the UI.
        def _clean_nickname(raw: object) -> str:
            return str(raw or "").strip().replace("\\'", "'").replace("\\\\", "")

        member_name_lookup = {
            str(row["beach_id"]): _clean_nickname(row["name"])
            for row in self._fetch_all("select beach_id, name from beaches")
        }

        parents: list[ParentBeachSummary] = []
        for row in rows:
            member_ids = [str(member_id) for member_id in _parse_json_list(row["member_beach_ids"])]
            member_names = [member_name_lookup.get(mid, "") for mid in member_ids]
            member_names = [n for n in member_names if n]
            member_forecasts = [
                forecast_lookup[beach_id] for beach_id in member_ids if beach_id in forecast_lookup
            ]
            worst_band: str | None = None
            worst_p: float | None = None
            worst_model_v: str | None = None
            if member_forecasts:
                worst_band, worst_p, worst_model_v = max(member_forecasts, key=lambda item: item[1])

            has_active = any(beach_id in active_beach_ids for beach_id in member_ids)
            if has_active:
                worst_band = "Advisory"

            # Pick advisory website from first active member station that has one
            advisory_website: str | None = None
            if has_active:
                for bid in member_ids:
                    url = advisory_websites.get(bid)
                    if url:
                        advisory_website = url
                        break

            # Trust curated `support_status` (set by derive_parent_beaches) as
            # the authoritative coverage label. A missing same-day forecast on
            # an otherwise-supported parent surfaces in the apps via a null
            # risk_band ("no current forecast"), not by relabeling the parent
            # as Not Supported.
            curated_support = str(row["support_status"]) if row["support_status"] else "unsupported"
            parents.append(
                ParentBeachSummary(
                    id=str(row["parent_beach_id"]),
                    name=str(row["name"]),
                    county=str(row["county"]),
                    region=str(row["region"]),
                    support_status=curated_support,
                    model_version=worst_model_v,
                    station_count=int(row["station_count"]),
                    member_beach_ids=member_ids,
                    member_beach_names=member_names,
                    latest_official_sample_at=_parse_datetime(row["latest_official_sample_at"]),
                    geometry=Point(
                        latitude=float(row["latitude"]),
                        longitude=float(row["longitude"]),
                    ),
                    risk_band=worst_band,
                    p_exceed=worst_p,
                    has_active_advisory=has_active,
                    advisory_website=advisory_website,
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

        active_set = self._active_advisory_beach_ids()
        website_map = self._active_advisory_websites()
        active_advisory = beach_id in active_set
        base_drivers = [str(item) for item in _parse_json_list(row.get("top_drivers"))]
        raw_p_exceed = _safe_float(row.get("p_exceed_raw"))
        model_risk_band = risk_band(raw_p_exceed) if raw_p_exceed is not None else str(row["risk_band"])
        advisory_website: str | None = None
        parent_has_advisory = False
        parent_advisory_url: str | None = None
        if active_advisory:
            drivers = ["Official health advisory is active for this station.", *base_drivers][:5]
            band = "Advisory"  # Authoritative county posting; UI surfaces the source link separately.
            advisory_website = website_map.get(beach_id)
        else:
            drivers = base_drivers
            band = model_risk_band
            parent_has_advisory, parent_advisory_url = self._parent_advisory_signal(
                beach_id, active_set, website_map
            )

        sample_age = _safe_int(row.get("sample_age_days"))
        if sample_age is None:
            sample_age = self._sample_age_days(beach_id, row.get("forecast_date"))

        return ForecastRecord(
            beach_id=beach_id,
            forecast_date=_parse_date(row.get("forecast_date")),
            risk_band=band,
            model_risk_band=model_risk_band if active_advisory else None,
            advisory_website=advisory_website,
            parent_has_active_advisory=parent_has_advisory,
            parent_advisory_website=parent_advisory_url,
            p_exceed=float(row["p_exceed"]),
            p_exceed_raw=_safe_float(row.get("p_exceed_raw")),
            advisory_floor_applied=_safe_bool(row.get("advisory_floor_applied"), default=False),
            p_exceed_lower=_safe_float(row.get("p_exceed_lower")),
            p_exceed_upper=_safe_float(row.get("p_exceed_upper")),
            predicted_log_enterococcus=_safe_float(row.get("predicted_log_enterococcus")),
            lower_prediction_interval=_safe_float(row.get("lower_prediction_interval")),
            upper_prediction_interval=_safe_float(row.get("upper_prediction_interval")),
            prediction_interval_level=_safe_float(row.get("prediction_interval_level")),
            top_drivers=drivers,
            model_version=str(row["model_version"]),
            forecast_generated_at=gen_at or datetime.now(UTC),
            forecast_age_hours=age_hours,
            official_advisory_active=active_advisory,
            forecast_label_mode=(
                "official_advisory_override"
                if active_advisory
                else str(row.get("forecast_label_mode") or "model")
            ),
            sample_age_days=sample_age,
            sample_recency_band=str(row.get("sample_recency_band") or sample_recency_band(sample_age)),
            is_beta_forecast=_safe_bool(row.get("is_beta_forecast"), default=True),
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
        active_advisory = beach_id in self._active_advisory_beach_ids()
        drivers = [
            "Official health advisory is active for this station." if active_advisory else None,
            "Latest official sample is above the marine threshold"
            if latest_value > self.stv_threshold
            else "Latest official sample remains below the marine threshold"
        ]
        drivers = [d for d in drivers if d]
        for key, label in (("weather", "weather"), ("storm_drain_flow", "storm drain flow")):
            value = latest[key] if key in latest.keys() else None
            if value and str(value).lower() not in ("nan", "none", ""):
                drivers.append(f"Field notes recorded {label} as {value}")

        return ForecastRecord(
            beach_id=beach_id,
            forecast_date=forecast_date,
            risk_band=("Advisory" if active_advisory else risk_band(p_exceed)),
            model_risk_band=(risk_band(p_exceed) if active_advisory else None),
            p_exceed=float(p_exceed),
            p_exceed_raw=float(p_exceed),
            advisory_floor_applied=False,
            predicted_log_enterococcus=log10(max(latest_value, 1.0)),
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
            top_drivers=drivers[:3],
        )

    def _sample_age_days(self, beach_id: str, forecast_date_value: object) -> int | None:
        row = self._fetch_one(
            "select latest_official_sample_at from beaches where beach_id = ?",
            (beach_id,),
        )
        if row is None:
            return None
        return self._sample_age_days_from_value(row["latest_official_sample_at"], forecast_date_value)

    def _sample_age_days_from_value(self, sample_time: object, forecast_date_value: object) -> int | None:
        try:
            sample_dt = _parse_datetime(sample_time)
            forecast_dt = _parse_datetime(forecast_date_value)
        except (ValueError, TypeError):
            return None
        if sample_dt is None or forecast_dt is None:
            return None
        return max(0, (forecast_dt.date() - sample_dt.date()).days)

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

        advisories = []
        for row in self._fetch_all(
            "select * from advisories_recent where beach_id = ? "
            "order by started_at desc limit 10",
            (beach_id,),
        ):
            adv = dict(row)
            advisories.append(
                AdvisoryRecord(
                    advisory_type=str(adv["advisory_type"]),
                    started_at=_parse_datetime(adv["started_at"]) or datetime.now(UTC),
                    ended_at=_parse_datetime(adv["ended_at"]),
                    status=str(adv["status"]),
                    advisory_website=_coerce_advisory_website(adv.get("advisory_website")),
                )
            )

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
                "wind_speed_mps": _safe_float(_row_get(row, "wind_speed_24h_max")),
                "wind_direction_deg": _safe_float(_row_get(row, "wind_direction_24h_mean")),
                "uv_index": _safe_float(_row_get(row, "uv_index_24h_max")),
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
        snapshot_row = self._fetch_one(
            "select payload from system_health where key = 'serving_snapshot'"
        )
        snapshot = json.loads(snapshot_row["payload"]) if snapshot_row is not None else None
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
                "is_beta_product": True,
                "active_advisories_count": int(active_count["count"]) if active_count else 0,
                "forecast_audit": audit,
                "repository_mode": "sqlite",
                "serving_snapshot": snapshot,
                **payload,
            }
        )
