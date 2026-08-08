from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.core.json_safe import write_json
from app.data.pipeline.county_corrections import correct_county
from app.data.pipeline.exceedance import (
    action_value_for,
    compute_exceeds_stv,
    is_pcr_measurement,
)
from app.data.pipeline.units_corrections import correct_units_series
from app.data.pipeline.schema_guard import validate_beach_day
from app.data.pipeline.spelling import correct_place_spelling


ENTEROCOCCUS_TERMS = {"enterococcus", "enterococci", "entero", "enterococus"}
MARINE_WATER_CLASSES = {"saltwater", "estuarine"}
MARINE_WATER_TYPE_TERMS = {"open coast", "sound", "bay", "inlet"}
MIN_PLAUSIBLE_SAMPLE_TIME = pd.Timestamp("2000-01-01")
MAX_FUTURE_SAMPLE_LEEWAY_DAYS = 2

COUNTY_ADVISORY_WEBSITES = {
    # Verified live via HEAD/GET on 2026-05-12. Counties whose pages I tried to
    # find but couldn't verify (404 / DNS errors at the time of the audit) fall
    # through to STATE_ADVISORY_WEBSITE below — better one extra click than a
    # 404 from inside our app.
    "Los Angeles": "http://publichealth.lacounty.gov/phcommon/public/eh/water_quality/beach_grades.cfm",
    "Orange": "https://ocbeachinfo.com/",
    "San Diego": "https://www.sdbeachinfo.com/",
    "Santa Barbara": "https://www.countyofsb.org/2263/Ocean-Water-Monitoring-Program",
    "Marin": "https://www.marincounty.org/depts/eh/services/beachsig",
    "Alameda": "https://acgov.org/aceh/water/swim.htm",
    "Monterey": "https://www.montereycountyhealth.com/183/Beach-Posting",
}

# CA-wide fallback when no county-specific page is known. Verified-real state
# resource that lets users look up any California beach.
STATE_ADVISORY_WEBSITE = "https://www.waterboards.ca.gov/water_issues/programs/beaches/"


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
    marine["name"] = marine["name"].map(correct_place_spelling)
    marine["county"] = (
        _column(marine, "CountyName").fillna(_column(marine, "County")).fillna("Unknown").map(correct_county)
    )
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
    marine["beach_name"] = _column(marine, "Beach_Name").map(_clean_text).map(correct_place_spelling)
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

    def _parent_support_status(sub: pd.DataFrame) -> str:
        statuses = set(sub["support_status"].dropna().astype(str).unique())
        if "production" in statuses:
            return "production"
        if "beta" in statuses:
            return "beta"
        return "unsupported"

    rows = []
    # dropna=False so stations with NaN usepa_id (typically inland lakes /
    # non-coastal monitoring sites that aren't in the EPA database) still
    # surface as singleton parents below instead of being silently dropped.
    for usepa_id, group in stations.groupby("usepa_id", dropna=False):
        usepa_id_str = "" if pd.isna(usepa_id) else str(usepa_id)
        if not usepa_id_str:
            # Stations without a EPA id (typically inland lakes / non-coastal
            # monitoring sites) still need to be reachable in the apps. Emit a
            # singleton parent per station so they appear in the parent feed
            # — they'll render with the gray "Not Supported" badge when no
            # forecast model covers them.
            for _, station in group.iterrows():
                beach_id = str(station["beach_id"])
                # County-wide aggregate placeholder stations (used internally
                # by the county-direct advisory scraper) aren't individual
                # beaches and shouldn't appear as separate cards in the apps.
                if "all-" in beach_id and "-county-" in beach_id and station.get("station_code", "").startswith("All_"):
                    continue
                # Prefer the display-friendly `name` field; fall back to
                # `beach_name` (often the BeachWatch raw name) only if name
                # is missing.
                display_name = (
                    str(station["name"]) if pd.notna(station.get("name")) and str(station["name"]).strip()
                    else str(station.get("beach_name") or beach_id)
                )
                rows.append({
                    "parent_beach_id": f"parent-{beach_id.lower()}",
                    "usepa_id": "",
                    "name": display_name,
                    "county": station["county"],
                    "region": station["region"],
                    "support_status": str(station.get("support_status") or "unsupported"),
                    "latitude": float(station["latitude"]) if pd.notna(station.get("latitude")) else None,
                    "longitude": float(station["longitude"]) if pd.notna(station.get("longitude")) else None,
                    "station_count": 1,
                    "member_beach_ids": [beach_id],
                    "latest_official_sample_at": (
                        station["latest_official_sample_at"]
                        if pd.notna(station.get("latest_official_sample_at"))
                        else None
                    ),
                })
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
                "support_status": _parent_support_status(sub),
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
    # Enterococcus is a non-negative count (MPN/CFU/copies). Negative results are
    # invalid sentinels (e.g. -1000 "not analyzed") — drop them so they don't
    # poison the lag/rolling features or the label.
    marine.loc[marine["value"] < 0, "value"] = np.nan
    marine["units"] = _column(marine, "Unit", "unknown").fillna("unknown").astype(str).str.strip()
    marine["method"] = _column(marine, "AnalysisMethod", "unknown").fillna("unknown").astype(str).str.strip()
    # Method-aware: PCR (copies) judged against the molecular threshold, not the
    # culture STV. See app.data.pipeline.exceedance.
    # Source correction before the predicate reads them: a culture method
    # cannot report copies (see units_corrections), and is_pcr_measurement
    # would otherwise judge such a row against 1413 instead of 104.
    marine["units"] = correct_units_series(marine["method"], marine["units"])
    marine["exceeds_stv"] = compute_exceeds_stv(
        marine["value"], marine["method"], marine["units"], stv_threshold
    )
    marine["county"] = _column(marine, "CountyName").fillna(_column(marine, "County")).map(correct_county)
    marine["station_name"] = _column(marine, "Station_Name").map(correct_place_spelling)
    marine["beach_name"] = _column(marine, "Beach_Name").map(correct_place_spelling)
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
    marine["county"] = _column(marine, "CountyName").fillna(_column(marine, "County")).map(correct_county)

    # Extract website if present, otherwise fall back to per-county mapping,
    # then to a state-level resource so we never serve a "no link" advisory.
    marine["advisory_website"] = _column(marine, "AdvisoryWebsite", "Unknown").fillna("Unknown")
    marine.loc[marine["advisory_website"] == "Unknown", "advisory_website"] = marine["county"].map(
        COUNTY_ADVISORY_WEBSITES
    ).fillna(STATE_ADVISORY_WEBSITE)

    return (
        marine[
            [
                "beach_id",
                "advisory_type",
                "started_at",
                "ended_at",
                "status",
                "cause",
                "county",
                "advisory_website",
            ]
        ]
        .dropna(subset=["started_at"])
        .reset_index(drop=True)
    )


ADVISORY_OPEN_ENDED_MAX_DAYS = 14


def fill_open_ended_advisory_end(
    started_at: pd.Series, ended_at: pd.Series
) -> pd.Series:
    """Effective end timestamp for an advisory, capping never-closed rows.

    Counties don't reliably log closure events, so an advisory with no
    ``ended_at`` is not necessarily still in effect. Open-ended rows are capped
    at ``started_at + 14 days`` — matching the serving override window and
    WHO/EPA acute-event guidance: anything not refreshed in two weeks is
    bureaucratic, not operational.

    This used to be a bare ``.fillna(Timestamp("2099-01-01"))`` here, which made
    every never-closed admin advisory (Tijuana plume, 2022 BSV postings)
    permanently active. training._refresh_candidate_advisory_features was fixed
    to cap them, but this copy — which builds beach_day.parquet, the TRAINING
    LABELS frame — was not, so the feature fired at 0.33 in training and 0.21 at
    serving, disagreeing on 12.4% of rows. One rule now, used by both.
    """
    started = pd.to_datetime(started_at)
    ended = pd.to_datetime(ended_at)
    capped = started + pd.Timedelta(days=ADVISORY_OPEN_ENDED_MAX_DAYS)
    return ended.fillna(capped)


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
    adv["ended_at_filled"] = fill_open_ended_advisory_end(
        adv["started_at"], adv["ended_at_ts"]
    )

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


def _attach_assay_identity(ranked: pd.DataFrame, stv_threshold: float) -> pd.DataFrame:
    """Add the assay-identity columns the day-collapse must carry through.

    ``exceeds_stv`` is not one label. Culture rows (Enterolert / EPA 1600 / MF,
    MPN or CFU per 100 mL) are judged against the 104 marine STV; San Diego
    ddPCR rows (copies per 100 mL) against the CDPH-developed, EPA Region 9
    approved 1413-copies BAV. Both action values are correct and neither is
    changed here — but until this function existed the two were merged into one
    numeric column with no marker, so every downstream feature
    (``enterococcus_value_lag_*``, ``log_enterococcus``, the 35/104-thresholded
    geomeans) mixed MPN with copies, and no metric could be stratified by regime.

    Adds three per-sample columns plus one per-beach-day column:

    ``is_pcr``
        Assay class of the row, from :func:`exceedance.is_pcr_measurement` — the
        *same* predicate that picked the threshold in
        :func:`exceedance.compute_exceeds_stv`. It must stay the same predicate:
        a bare ``method == "ddPCR"`` comparison here would disagree with the
        label on ``MCB-ddPCR SOP018-000`` rows and on rows that declare only
        ``copies/100 mL`` units, silently re-splitting the population against
        the thresholds actually applied.
    ``_label_method`` / ``_label_units``
        The raw method/units strings, carried under private names so the
        day-collapse can rename them to ``label_method`` / ``label_units`` — the
        assay of the sample that *won* the collapse, not an arbitrary one.
    ``assay_disagreement``
        True when that beach-day carried both a culture and a PCR sample and the
        two classes disagreed on ``exceeds_stv``. Compared worst-of-each-class,
        matching how the label itself is built. This is the per-row marker for
        the ~50% paired-sample agreement rate; it is a *flag*, not a correction —
        the collapse rule is deliberately unchanged.

    ``_action_value``
        The number *this row* is judged against — 104 for culture, 1413 for
        ddPCR — from the single :func:`exceedance.action_value_for` mapping. The
        day-collapse divides by it to rank same-day samples on a common
        dimensionless scale (see :func:`build_beach_day_frame`).

    ``method``/``units`` are tolerated as absent: the national WQP path adds them
    as null, but a caller that omits them entirely gets an all-culture frame
    rather than a KeyError.
    """
    frame = ranked
    method = (
        frame["method"]
        if "method" in frame.columns
        else pd.Series(pd.NA, index=frame.index, dtype="object")
    )
    units = (
        frame["units"]
        if "units" in frame.columns
        else pd.Series(pd.NA, index=frame.index, dtype="object")
    )
    frame["_label_method"] = method
    frame["_label_units"] = units
    frame["is_pcr"] = is_pcr_measurement(method, units).fillna(False).astype(bool)
    frame["_action_value"] = action_value_for(method, units, stv_threshold)

    pcr = frame["is_pcr"].to_numpy(dtype=bool)
    exceed = frame["_exceed_rank"].to_numpy(dtype=float)
    if not pcr.any() or pcr.all():
        # Single-assay frame — no beach-day can hold both classes, so skip the
        # per-day aggregation entirely (this is the common case: only San Diego
        # runs both).
        frame["assay_disagreement"] = False
        return frame

    frame["_exceed_culture"] = np.where(pcr, np.nan, exceed)
    frame["_exceed_pcr"] = np.where(pcr, exceed, np.nan)
    per_day = frame.groupby(["beach_id", "sample_date"], sort=False)
    worst_culture = per_day["_exceed_culture"].transform("max")
    worst_pcr = per_day["_exceed_pcr"].transform("max")
    frame["assay_disagreement"] = (
        worst_culture.notna() & worst_pcr.notna() & (worst_culture != worst_pcr)
    ).to_numpy(dtype=bool)
    return frame.drop(columns=["_exceed_culture", "_exceed_pcr"])


def build_beach_day_frame(
    observations: pd.DataFrame,
    stations: pd.DataFrame,
    advisories: pd.DataFrame,
    stv_threshold: float | None = None,
) -> pd.DataFrame:
    if observations.empty:
        return pd.DataFrame()

    # Collapse multiple same-day samples to one training row using ANY-exceedance,
    # not the chronologically-last sample. A beach sampled twice in a day where an
    # earlier sample exceeded the STV but a later resample came back clean must be
    # labeled EXCEEDED — this is a public-health, false-negative-averse target, so
    # a morning exceedance is never erased by a clean afternoon reading (the prior
    # `.tail(1)` rule flipped 1,009 such beach-days to "safe", 100% in the
    # false-negative direction). We represent the day with its WORST sample so the
    # kept `enterococcus_value` / `exceeds_stv` and every value-derived lag/geomean
    # feature stay mutually consistent. `sample_time` is the final tiebreak so the
    # pick is deterministic even when same-day samples share an identical timestamp.
    #
    # "Worst" is ranked on TWO keys, and both must be on the same scale:
    #
    #   1. `_exceed_rank` — the method-aware `exceeds_stv`, i.e. `value >
    #      action_value` (104 culture / 1413 ddPCR).
    #   2. `_value_rank`  — the tiebreak among rows that agree on (1).
    #
    # Key 2 used to be the RAW value, which compares ddPCR *copies* against
    # culture *MPN*. Those are different units on different scales with no
    # constant conversion between them (Verbyla & Lacarra 2026 fit a log-log
    # slope of 0.52 at one site vs the county-wide ICE's 16x-steeper relation —
    # see CLAUDE.md), so the comparison was meaningless: copy counts simply run
    # numerically larger, and ddPCR won 590 of the 591 mixed-assay days on which
    # the two assays AGREED about the label, purely on magnitude (median 2,501
    # copies vs 10 MPN).
    #
    # The label never moved from this — key 1 dominates — but the NUMBER kept in
    # `enterococcus_value` did, and that column feeds `enterococcus_value_lag_*`,
    # `enterococcus_value_last_obs`, `log_enterococcus` and the 35/104-thresholded
    # geomeans. So on those days a copies count was seated in an otherwise-MPN
    # column by an arbitrary unit artifact.
    #
    # Key 2 is now `value / action_value`: each result expressed as a multiple of
    # the number IT is judged against. This is the only normalisation available
    # that does not require inventing a copies<->MPN conversion the data cannot
    # support (three defensible estimators span 21x), and it makes the two keys
    # the SAME monotone function of the row — key 1 is exactly `ratio > 1`, so
    # the tiebreak is now a refinement of the primary key rather than a second,
    # contradictory scale. Ties within an assay are unaffected (dividing every
    # row of one assay by the same constant preserves their order), so this can
    # only change which sample represents a MIXED-assay day.
    _ranked = observations.copy()
    _ranked["_exceed_rank"] = (
        _ranked["exceeds_stv"].fillna(False).astype(bool).astype(int)
    )
    if stv_threshold is None:
        stv_threshold = float(get_settings().epa_marine_enterococcus_stv)
    _ranked = _attach_assay_identity(_ranked, stv_threshold)
    _ranked["_value_rank"] = (
        pd.to_numeric(_ranked["value"], errors="coerce") / _ranked["_action_value"]
    ).fillna(float("-inf"))
    per_day_observation = (
        _ranked.sort_values(["_exceed_rank", "_value_rank", "sample_time"])
        .groupby(["beach_id", "sample_date"], as_index=False)
        .tail(1)
    )[
        [
            "beach_id",
            "sample_date",
            "sample_time",
            "value",
            "exceeds_stv",
            "_label_method",
            "_label_units",
            "is_pcr",
            "assay_disagreement",
            "weather",
            "storm_drain_flow",
            "tidal_height",
            "surf_height_observed",
            "turbidity_observed",
            "odor",
            "water_color",
        ]
    ].rename(
        columns={
            "value": "enterococcus_value",
            "_label_method": "label_method",
            "_label_units": "label_units",
        }
    )

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
    # Final county-correction pass — fixes jurisdiction-as-county values
    # ("Long Beach City" -> "Los Angeles") regardless of which path set them
    # (BeachWatch, CEDEN merge, or id-slug fallback). beach_id keys unchanged.
    # derive_parent_beaches() below then inherits the corrected county.
    for _frame in (stations, observations, beach_day):
        if "county" in _frame.columns:
            _frame["county"] = _frame["county"].map(correct_county)
    stations.to_parquet(curated_dir / "beaches.parquet", index=False)
    derive_parent_beaches(stations).to_parquet(curated_dir / "parent_beaches.parquet", index=False)
    observations.to_parquet(curated_dir / "observations.parquet", index=False)
    advisories.to_parquet(curated_dir / "advisories.parquet", index=False)
    # Schema guard: hard-fail on a structurally unusable training artifact
    # (empty / missing primary key / missing label); warn-only on absent or
    # all-NaN feature columns (a connector outage is not a reason to break the
    # live daily run).
    validate_beach_day(beach_day)
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
    write_json(curated_dir / "system_health.json", payload)
