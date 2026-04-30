from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ENTEROCOCCUS_TERMS = {"enterococcus", "enterococci", "entero", "enterococus"}
MARINE_WATER_CLASSES = {"saltwater", "estuarine"}
MARINE_WATER_TYPE_TERMS = {"open coast", "sound", "bay", "inlet"}
MIN_PLAUSIBLE_SAMPLE_TIME = pd.Timestamp("2000-01-01")
MAX_FUTURE_SAMPLE_LEEWAY_DAYS = 2


def _column(frame: pd.DataFrame, name: str, default: str | None = None) -> pd.Series:
    if name in frame.columns:
        return frame[name]
    return pd.Series([default] * len(frame), index=frame.index, dtype="object")


def _clean_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "notavailable"}:
        return None
    return text


def _to_float(value: Any) -> float | None:
    text = _clean_text(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _slugify(*parts: Any) -> str:
    joined = "-".join(part for part in (_clean_text(item) or "" for item in parts) if part)
    slug = re.sub(r"[^a-z0-9]+", "-", joined.lower()).strip("-")
    return slug or "unknown-beach"


def _canonical_parameter(value: Any) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    normalized = re.sub(r"[^a-z]", "", text.lower())
    if any(term in normalized for term in ENTEROCOCCUS_TERMS):
        return "enterococcus"
    return None


def _parse_datetime(date_value: Any, time_value: Any) -> datetime | None:
    date_text = _clean_text(date_value)
    if date_text is None:
        return None
    time_text = _clean_text(time_value) or "00:00:00"
    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(f"{date_text} {time_text}", fmt)
        except ValueError:
            continue
    return None


def _plausible_datetime_mask(values: pd.Series) -> pd.Series:
    max_plausible_time = pd.Timestamp.now(tz="UTC").tz_localize(None) + pd.Timedelta(
        days=MAX_FUTURE_SAMPLE_LEEWAY_DAYS
    )
    return values.between(MIN_PLAUSIBLE_SAMPLE_TIME, max_plausible_time)


def is_marine_station(frame: pd.DataFrame) -> pd.Series:
    water_class = _column(frame, "WaterBodyClass", "").fillna("")
    water_type = _column(frame, "WaterBodyType", "").fillna("")
    water_class = water_class.astype(str).str.lower()
    water_type = water_type.astype(str).str.lower()
    return water_class.isin(MARINE_WATER_CLASSES) | water_type.apply(
        lambda value: any(term in value for term in MARINE_WATER_TYPE_TERMS)
    )


def derive_beach_id(frame: pd.DataFrame) -> pd.Series:
    return pd.Series(
        [
            _slugify(
                row.get("USEPAID"),
                row.get("CountyName") or row.get("County"),
                row.get("Beach_Name") or row.get("BeachName"),
                row.get("Station_Name"),
            )
            for _, row in frame.iterrows()
        ],
        index=frame.index,
        dtype="string",
    )


def normalize_station_metadata(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    marine = frame.loc[is_marine_station(frame)].copy()
    marine["beach_id"] = derive_beach_id(marine)
    desc = _column(marine, "Station_Description").replace(r"^\s*$", pd.NA, regex=True)
    st_name = _column(marine, "Station_Name").replace(r"^\s*$", pd.NA, regex=True)
    b_name = _column(marine, "Beach_Name").replace(r"^\s*$", pd.NA, regex=True)

    def _best_name(d, s, b):
        d_str = str(d).strip() if pd.notna(d) else ""
        s_str = str(s).strip() if pd.notna(s) else ""
        b_str = str(b).strip() if pd.notna(b) else ""

        if d_str and d_str.lower() != b_str.lower() and d_str.lower() != s_str.lower():
            return d_str
        if s_str:
            return s_str
        if b_str:
            return b_str
        return "Unknown Station"

    marine["name"] = [_best_name(d, s, b) for d, s, b in zip(desc, st_name, b_name, strict=False)]
    marine["county"] = _column(marine, "CountyName").fillna(_column(marine, "County")).fillna("Unknown")
    marine["region"] = _column(marine, "Regional Board Name").fillna(_column(marine, "Regional Board"))
    marine["support_status"] = _column(marine, "Status", "Unknown").fillna("Unknown").map(
        lambda status: "production" if str(status).lower() == "active" else "unsupported"
    )
    marine["latitude"] = _column(marine, "Station_UpperLat").map(_to_float).fillna(
        _column(marine, "Beach_UpperLat").map(_to_float)
    )
    marine["longitude"] = _column(marine, "Station_UpperLon").map(_to_float).fillna(
        _column(marine, "Beach_UpperLon").map(_to_float)
    )
    marine["latest_official_sample_at"] = pd.NaT
    marine["usepa_id"] = _column(marine, "USEPAID").map(_clean_text)
    marine["station_code"] = _column(marine, "Station_Name").map(_clean_text)
    marine["beach_name"] = _column(marine, "Beach_Name").map(_clean_text)
    marine["water_body_class"] = _column(marine, "WaterBodyClass").map(_clean_text)
    marine["water_body_type"] = _column(marine, "WaterBodyType").map(_clean_text)
    marine["agency_name"] = _column(marine, "Agency_Name").fillna(
        _column(marine, "Beach_AgencyName")
    ).map(_clean_text)
    marine["zip_code"] = _column(marine, "Zip").map(_clean_text)
    return (
        marine[
            [
                "beach_id",
                "name",
                "county",
                "region",
                "support_status",
                "latest_official_sample_at",
                "latitude",
                "longitude",
                "usepa_id",
                "station_code",
                "beach_name",
                "water_body_class",
                "water_body_type",
                "agency_name",
                "zip_code",
            ]
        ]
        .drop_duplicates(subset=["beach_id"])
        .reset_index(drop=True)
    )


_DBSCAN_EPS_KM = 3.0
_DBSCAN_EPS_RAD = _DBSCAN_EPS_KM / 6371.0
_SPLIT_THRESHOLD_KM = 5.0  # only sub-cluster if group spans more than this


def derive_parent_beaches(stations: pd.DataFrame) -> pd.DataFrame:
    """Group station rows into logical parent beaches using usepa_id.

    Uses DBSCAN (eps=3 km) to split usepa_id groups that span >5 km into
    geographic sub-clusters, each becoming its own parent beach entry with a
    directional suffix (· North / · South).
    """
    if stations.empty:
        return pd.DataFrame()

    try:
        from sklearn.cluster import DBSCAN as _DBSCAN
        import numpy as _np
        _dbscan_available = True
    except ImportError:
        _dbscan_available = False

    def _canonical_name(group: pd.DataFrame) -> str:
        if "beach_name" in group.columns:
            beach_names = group["beach_name"].dropna().unique().tolist()
            if beach_names:
                return max(beach_names, key=len)
        first_id = group["beach_id"].iloc[0]
        slug = re.sub(r"^ca\d+-", "", first_id)
        county_slug = str(group["county"].iloc[0]).lower().replace(" ", "-")
        if slug.startswith(county_slug + "-"):
            slug = slug[len(county_slug) + 1:]
        station_slug = re.sub(r"[^a-z0-9]+", "-", str(group["name"].iloc[0]).lower()).strip("-")
        if station_slug and slug.endswith("-" + station_slug):
            slug = slug[:-(len(station_slug) + 1)]
        derived = slug.replace("-", " ").title()
        return derived if derived else (group["name"].iloc[0] if not group["name"].empty else "Unknown Beach")

    def _spread_km(group: pd.DataFrame) -> float:
        coords = group[["latitude", "longitude"]].dropna()
        if len(coords) < 2:
            return 0.0
        lat_km = (coords["latitude"].max() - coords["latitude"].min()) * 111.0
        lon_km = (coords["longitude"].max() - coords["longitude"].min()) * 88.0
        return float((lat_km ** 2 + lon_km ** 2) ** 0.5)

    def _sub_clusters(group: pd.DataFrame) -> list[pd.DataFrame]:
        """Return list of sub-group DataFrames; splits via DBSCAN if warranted."""
        if not _dbscan_available or _spread_km(group) <= _SPLIT_THRESHOLD_KM:
            return [group]
        coords = group[["latitude", "longitude"]].dropna()
        if len(coords) < 2:
            return [group]
        coords_rad = _np.radians(coords.values)
        labels = _DBSCAN(eps=_DBSCAN_EPS_RAD, min_samples=1, metric="haversine").fit_predict(coords_rad)
        group = group.copy()
        group.loc[coords.index, "_cluster"] = labels
        group["_cluster"] = group["_cluster"].fillna(-1).astype(int)
        unique = sorted(cl for cl in group["_cluster"].unique() if cl >= 0)
        if len(unique) <= 1:
            return [group]
        return [group[group["_cluster"] == cl].copy() for cl in unique]

    _DIRECTION_LABELS = ["North", "South", "East", "West", "Central"]

    rows = []
    for usepa_id, group in stations.groupby("usepa_id"):
        if not usepa_id:
            continue

        base_name = _canonical_name(group)
        sub_groups = _sub_clusters(group)

        # Sort sub-groups north→south by centroid latitude so suffixes are stable
        if len(sub_groups) > 1:
            sub_groups = sorted(sub_groups, key=lambda sg: sg["latitude"].mean(), reverse=True)

        for rank, sub in enumerate(sub_groups):
            member_ids = sub["beach_id"].tolist()
            n_subs = len(sub_groups)
            if n_subs == 1:
                name = base_name
                parent_id = f"parent-{str(usepa_id).lower()}"
            else:
                direction = _DIRECTION_LABELS[rank] if rank < len(_DIRECTION_LABELS) else str(rank + 1)
                name = f"{base_name} · {direction}"
                parent_id = f"parent-{str(usepa_id).lower()}-{rank + 1}"

            rows.append({
                "parent_beach_id": parent_id,
                "usepa_id": usepa_id,
                "name": name,
                "county": sub["county"].iloc[0],
                "region": sub["region"].iloc[0],
                "support_status": (
                    "production" if (sub["support_status"] == "production").any() else "unsupported"
                ),
                "latitude": float(sub["latitude"].dropna().mean()) if sub["latitude"].notna().any() else None,
                "longitude": float(sub["longitude"].dropna().mean()) if sub["longitude"].notna().any() else None,
                "station_count": len(member_ids),
                "member_beach_ids": member_ids,
                "latest_official_sample_at": (
                    sub["latest_official_sample_at"].dropna().max()
                    if sub["latest_official_sample_at"].notna().any()
                    else None
                ),
            })

    return pd.DataFrame(rows).reset_index(drop=True)


def normalize_bacteria_results(frame: pd.DataFrame, stv_threshold: float) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    marine = frame.loc[is_marine_station(frame)].copy()
    marine["analyte"] = marine["Parameter"].map(_canonical_parameter)
    marine = marine.loc[marine["analyte"] == "enterococcus"].copy()
    if marine.empty:
        return pd.DataFrame()

    marine["beach_id"] = derive_beach_id(marine)
    marine["sample_time"] = [
        _parse_datetime(date_value, time_value)
        for date_value, time_value in zip(marine["SampleDate"], marine["StartTime"], strict=False)
    ]
    marine["sample_time"] = pd.to_datetime(marine["sample_time"], errors="coerce")
    marine = marine.loc[_plausible_datetime_mask(marine["sample_time"])].copy()
    marine["sample_date"] = marine["sample_time"].dt.date
    marine["value"] = _column(marine, "Result").map(_to_float)
    marine["units"] = _column(marine, "Unit", "unknown").fillna("unknown").astype(str).str.strip()
    marine["method"] = _column(marine, "AnalysisMethod", "unknown").fillna("unknown").astype(str).str.strip()
    marine["exceeds_stv"] = marine["value"].fillna(0).gt(stv_threshold)
    marine["county"] = _column(marine, "CountyName").fillna(_column(marine, "County"))
    marine["station_name"] = _column(marine, "Station_Name")
    marine["beach_name"] = _column(marine, "Beach_Name")
    marine["usepa_id"] = _column(marine, "USEPAID").map(_clean_text)
    marine["station_code"] = _column(marine, "Station_Name").map(_clean_text)
    marine["data_source"] = "BeachWatch"
    marine["weather"] = _column(marine, "Weather").map(_clean_text)
    marine["storm_drain_flow"] = _column(marine, "StormDrainFlow").map(_clean_text)
    marine["tidal_height"] = _column(marine, "TidalHeight").map(_to_float)
    marine["surf_height_observed"] = _column(marine, "SurfHeight").map(_to_float)
    marine["turbidity_observed"] = _column(marine, "Turbidity").map(_to_float)
    marine["odor"] = _column(marine, "Odor").map(_clean_text)
    marine["water_color"] = _column(marine, "WaterColor").map(_clean_text)
    return (
        marine[
            [
                "beach_id",
                "sample_time",
                "sample_date",
                "analyte",
                "method",
                "units",
                "value",
                "exceeds_stv",
                "county",
                "station_name",
                "beach_name",
                "usepa_id",
                "station_code",
                "weather",
                "storm_drain_flow",
                "tidal_height",
                "surf_height_observed",
                "turbidity_observed",
                "odor",
                "water_color",
                "data_source",
            ]
        ]
        .dropna(subset=["sample_time", "value"])
        .sort_values(["beach_id", "sample_time"])
        .reset_index(drop=True)
    )


def normalize_advisories(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    marine = frame.loc[is_marine_station(frame)].copy()
    marine["beach_id"] = derive_beach_id(marine)
    marine["started_at"] = [
        _parse_datetime(date_value, time_value)
        for date_value, time_value in zip(marine["DateofAdvisory"], marine["TimeofAdvisory"], strict=False)
    ]
    marine["ended_at"] = [
        _parse_datetime(date_value, time_value)
        for date_value, time_value in zip(marine["DateOpened"], marine["TimeOpened"], strict=False)
    ]
    
    marine["started_at"] = pd.to_datetime(marine["started_at"], errors="coerce")
    marine["ended_at"] = pd.to_datetime(marine["ended_at"], errors="coerce")
    marine = marine.loc[_plausible_datetime_mask(marine["started_at"])].copy()
    
    marine["status"] = marine["ended_at"].isna().map(lambda active: "active" if active else "historical")
    marine["advisory_type"] = _column(marine, "AdvisoryType", "Unknown").fillna("Unknown")
    marine["cause"] = _column(marine, "AdvisoryCause", "Unknown").fillna("Unknown")
    marine["county"] = _column(marine, "CountyName").fillna(_column(marine, "County"))
    return (
        marine[["beach_id", "advisory_type", "started_at", "ended_at", "status", "cause", "county"]]
        .dropna(subset=["started_at"])
        .reset_index(drop=True)
    )


def _advisory_temporal_features(beach_day: pd.DataFrame, advisories: pd.DataFrame) -> pd.DataFrame:
    """Add per-(beach_id, sample_date) advisory activity features.

    advisory_active_prev_14d: 1 if any advisory overlapped the 14-day window
      before this sample — a lagged signal with no label leakage.
    days_since_advisory_closed: days since the most-recently-closed advisory
      for this beach (NaN if no advisory ever closed, i.e. all still open or
      none at all).
    """
    bd = beach_day.copy()
    bd["sample_date"] = pd.to_datetime(bd["sample_date"])

    if advisories.empty:
        bd["advisory_active_prev_14d"] = 0
        bd["days_since_advisory_closed"] = np.nan
        return bd

    adv = advisories[["beach_id", "started_at", "ended_at"]].copy()
    adv["started_at"] = pd.to_datetime(adv["started_at"])
    adv["ended_at_ts"] = pd.to_datetime(adv["ended_at"])
    adv["ended_at_filled"] = adv["ended_at_ts"].fillna(pd.Timestamp("2099-01-01"))

    # Cross-merge within beach_id; _row tracks the originating beach_day index.
    key = bd[["beach_id", "sample_date"]].copy()
    key["_row"] = np.arange(len(key))
    crossed = key.merge(adv, on="beach_id", how="left")

    crossed["_window_start"] = crossed["sample_date"] - pd.Timedelta(days=14)
    crossed["_hit"] = (
        (crossed["started_at"] < crossed["sample_date"])
        & (crossed["ended_at_filled"] > crossed["_window_start"])
    )
    active_14d = crossed.groupby("_row")["_hit"].any().astype(int)
    bd["advisory_active_prev_14d"] = active_14d.reindex(range(len(bd))).fillna(0).astype(int).to_numpy()

    closed = crossed[crossed["ended_at_ts"].notna()].copy()
    closed["_days"] = (closed["sample_date"] - closed["ended_at_ts"]).dt.days
    closed = closed[closed["_days"] >= 0]
    if not closed.empty:
        min_days = closed.groupby("_row")["_days"].min()
        bd["days_since_advisory_closed"] = min_days.reindex(range(len(bd))).to_numpy(dtype=float)
    else:
        bd["days_since_advisory_closed"] = np.nan

    return bd


def build_beach_day_frame(
    observations: pd.DataFrame, stations: pd.DataFrame, advisories: pd.DataFrame
) -> pd.DataFrame:
    if observations.empty:
        return pd.DataFrame()

    per_day_observation = (
        observations.sort_values("sample_time")
        .groupby(["beach_id", "sample_date"], as_index=False)
        .tail(1)
    )[
        [
            "beach_id",
            "sample_date",
            "sample_time",
            "value",
            "exceeds_stv",
            "weather",
            "storm_drain_flow",
            "tidal_height",
            "surf_height_observed",
            "turbidity_observed",
            "odor",
            "water_color",
        ]
    ].rename(columns={"value": "enterococcus_value"})

    station_columns = [
        "beach_id",
        "name",
        "county",
        "region",
        "latitude",
        "longitude",
        "support_status",
        "usepa_id",
        "water_body_class",
        "water_body_type",
        "agency_name",
        "zip_code",
    ]
    beach_day = per_day_observation.merge(
        stations.reindex(columns=station_columns),
        on="beach_id",
        how="left",
    )
    advisory_counts = advisories.groupby("beach_id").size().rename("historical_advisory_count")
    beach_day = beach_day.merge(advisory_counts, on="beach_id", how="left")
    beach_day["historical_advisory_count"] = beach_day["historical_advisory_count"].fillna(0).astype(int)
    beach_day = beach_day.sort_values(["county", "name", "sample_date"]).reset_index(drop=True)
    return _advisory_temporal_features(beach_day, advisories)


def write_curated_bundle(
    curated_dir: Path,
    stations: pd.DataFrame,
    observations: pd.DataFrame,
    advisories: pd.DataFrame,
    beach_day: pd.DataFrame,
    model_registry: dict[str, Any] | None = None,
) -> None:
    curated_dir.mkdir(parents=True, exist_ok=True)
    stations.to_parquet(curated_dir / "beaches.parquet", index=False)
    derive_parent_beaches(stations).to_parquet(curated_dir / "parent_beaches.parquet", index=False)
    observations.to_parquet(curated_dir / "observations.parquet", index=False)
    advisories.to_parquet(curated_dir / "advisories.parquet", index=False)
    beach_day.to_parquet(curated_dir / "beach_day.parquet", index=False)
    payload = {
        "pipeline_freshness": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_freshness": {
            "beaches": datetime.now(UTC).isoformat(timespec="seconds"),
            "observations": datetime.now(UTC).isoformat(timespec="seconds"),
            "advisories": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "model_registry": model_registry
        or {"production_model": "derived-persistence-v0", "candidate_models": [], "metrics": {}},
    }
    (curated_dir / "system_health.json").write_text(json.dumps(payload, indent=2))
