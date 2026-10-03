"""Bake the per-beach static JSON files the web app consumes.

`shorelife-web/public/data/beaches.json` (and parent_beaches.json,
regional_summary.json) are read at Next.js build time and shipped as part of
the static export. They drive the home-page "Featured beach" card and the map
view. They MUST include the Advisory band override applied at serve time —
otherwise the map shows stale "Very High" labels for advisory-active beaches.

This script reads the curated parquets, applies the same override logic as
`app.repositories.curated_repository.CuratedBeachRepository`, and emits the
three JSON files to a target directory.

Run from `backend/`:
    .venv/bin/python -m scripts.bake_web_static --curated ../data/curated \
        --out ../../shorelife-web/public/data
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Vendored inline so this script can run in the web's CI without surf_health
# backend deps. Keep in sync with backend/app/ml/calibration.py.
_LOW_THRESHOLD = 0.20
_HIGH_THRESHOLD = 0.30
_VERY_HIGH_THRESHOLD = 0.70


def risk_band(probability: float | None) -> str | None:
    if probability is None:
        return None
    try:
        p = float(probability)
    except (TypeError, ValueError):
        return None
    if math.isnan(p):
        return None
    if p < _LOW_THRESHOLD:
        return "Low"
    if p < _HIGH_THRESHOLD:
        return "Moderate"
    if p < _VERY_HIGH_THRESHOLD:
        return "High"
    return "Very High"


def advisory_floored_probability(
    probability: float | None, advisory_active: bool
) -> tuple[float | None, bool]:
    """Vendored twin of app.ml.calibration.advisory_floored_probability.

    Keep in sync with the backend copy. Lifts p_exceed to the High cutpoint while
    a posting is active, so a posted beach can never render Low/Moderate now that
    risk_band stays the model's band instead of being replaced by "Advisory".
    """
    if not advisory_active or probability is None:
        return probability, False
    try:
        p = float(probability)
    except (TypeError, ValueError):
        return probability, False
    if math.isnan(p) or p >= _HIGH_THRESHOLD:
        return probability, False
    return _HIGH_THRESHOLD, True


OFFICIAL_ADVISORY_DRIVER = "Official health advisory is active for this station."
# Keep in lockstep with `curated_repository.ADVISORY_MAX_AGE_DAYS` and
# `serving_repository._ACTIVE_ADVISORY_WINDOW_DAYS`; that docstring carries the
# rationale. `test_bake_conditions_map` pins this against the map baker's copy.
ACTIVE_WINDOW_DAYS = 7


def _safe(value):
    """Convert pandas NaN/NaT/inf to None for JSON; pass scalars through."""
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if hasattr(value, "tolist"):
        return _safe(value.tolist())
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _finite_or_none(value) -> float | None:
    """Return value as a finite float if present and parseable (INCLUDING 0.0),
    else None. Reuses ``_safe`` (which already maps NaN/inf/NaT -> None) so a
    genuine raw probability of exactly 0.0 is preserved rather than treated as a
    missing value by a truthiness check.
    """
    safe = _safe(value)
    if safe is None:
        return None
    try:
        f = float(safe)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _active_advisory_set(advisories: pd.DataFrame) -> tuple[set[str], dict[str, str]]:
    """Return (set of beach_ids with currently-active advisory, beach_id->website map).

    Mirrors `serving_repository._active_advisory_beach_ids` semantics:
    status='active', not explicitly lifted, AND started_at within
    ACTIVE_WINDOW_DAYS. Counties don't reliably log closures, so the age
    window prevents zombie advisories from hanging forever.
    """
    if advisories.empty:
        return set(), {}
    a = advisories.copy()
    a["started_at"] = pd.to_datetime(a["started_at"], errors="coerce")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(days=ACTIVE_WINDOW_DAYS)
    is_active = a["status"] == "active"
    # An explicit lift wins over everything, closures included: when the county
    # logs `ended_at` we drop the advisory immediately instead of holding it
    # for the rest of the age window. NaT means "never lifted" and must
    # survive, so test for lifted-ness and negate it.
    if "ended_at" in a.columns:
        ended = pd.to_datetime(a["ended_at"], errors="coerce")
        is_active = is_active & ~(ended.notna() & (ended <= now))
    # Closures bypass the acute age window — they describe ongoing hazards
    # (Tijuana Slough since Oct 2025, etc.) and persist until the scraper
    # stops seeing them. Postings still get the age gate.
    advisory_type = a.get("advisory_type", pd.Series("", index=a.index))
    is_closure = advisory_type.fillna("").str.contains("closure", case=False, na=False)
    active = a[is_active & (is_closure | (a["started_at"] >= cutoff))]
    ids = {str(b) for b in active["beach_id"].dropna()}
    # Per-beach: first non-null website
    websites: dict[str, str] = {}
    for _, row in active.iterrows():
        bid = str(row.get("beach_id") or "")
        url = row.get("advisory_website")
        if bid and url and bid not in websites and not pd.isna(url):
            websites[bid] = str(url)
    return ids, websites


def _member_ids(raw) -> list[str]:
    """Normalize the parquet member_beach_ids cell (numpy array / list /
    JSON string) to a list of str."""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return [raw]
    try:
        return [str(x) for x in list(raw)]
    except TypeError:
        return []


def _sibling_map(parent_df: pd.DataFrame) -> dict[str, list[str]]:
    """station beach_id -> every member beach_id under the same parent.

    Drives the beach-wide advisory badge: a station with no posting of its own
    still shows "Advisory (beach-wide)" when a sibling under the same parent is
    posted, because the county and the city sometimes sample different points
    of one beach and disagree. Membership comes from parent_beaches.parquet,
    the exact grouping the API uses, so the badge cannot drift from the parent
    card's own has_active_advisory rollup.
    """
    siblings: dict[str, list[str]] = {}
    if parent_df.empty or "member_beach_ids" not in parent_df.columns:
        return siblings
    for _, pr in parent_df.iterrows():
        members = _member_ids(pr.get("member_beach_ids"))
        for mid in members:
            siblings[mid] = members
    return siblings


def _build_forecast_block(
    fc_row: pd.Series,
    has_active_advisory: bool,
    parent_has_active_advisory: bool = False,
    parent_advisory_website: str | None = None,
) -> dict:
    """Mirror curated_repository.get_forecast's override logic."""
    row = {k: _safe(v) for k, v in fc_row.items()}
    # Carried on the forecast block as well as the station row because the web
    # reads the advisory badge off `forecast`, matching the API's ForecastRecord.
    row["parent_has_active_advisory"] = parent_has_active_advisory
    row["parent_advisory_website"] = parent_advisory_website
    # Prefer the genuine raw model probability whenever it is present and a
    # finite number — INCLUDING exactly 0.0 (isotonic's lowest bin can emit it).
    # A truthiness `or` would drop a real 0.0 through to p_exceed, which is the
    # advisory-FLOORED served value (e.g. 0.30) and would mislabel a 'Low'
    # forecast as 'High', diverging from the production API's None/NaN check.
    raw_p = _finite_or_none(row.get("p_exceed_raw"))
    if raw_p is None:
        raw_p = _finite_or_none(row.get("p_exceed"))
    model_band = risk_band(raw_p) if raw_p is not None else row.get("risk_band")
    if has_active_advisory:
        # risk_band stays the MODEL's band; the posting is signalled by
        # official_advisory_active, which the UI renders as a separate badge.
        # advisory_floored_probability guarantees the band cannot read Low or
        # Moderate under an active posting, so badge and band can't contradict.
        floored_p, floor_applied = advisory_floored_probability(
            raw_p if raw_p is not None else 0.0, True
        )
        row["official_advisory_active"] = True
        row["p_exceed"] = floored_p
        row["risk_band"] = risk_band(floored_p)
        # Retained for API compatibility; equals risk_band now that the band is
        # never replaced. Clients should read official_advisory_active instead.
        row["model_risk_band"] = model_band
        row["advisory_floor_applied"] = bool(row.get("advisory_floor_applied")) or floor_applied
        row["forecast_label_mode"] = "official_advisory_override"
        drivers = list(row.get("top_drivers") or [])
        drivers = [d for d in drivers if d != OFFICIAL_ADVISORY_DRIVER]
        row["top_drivers"] = [OFFICIAL_ADVISORY_DRIVER, *drivers][:5]
    else:
        row["official_advisory_active"] = False
        row["model_risk_band"] = None
    return row


def bake(curated: Path, out: Path, with_details: bool = False) -> None:
    beaches = pd.read_parquet(curated / "beaches.parquet")
    forecasts = pd.read_parquet(curated / "forecasts.parquet")
    advisories = pd.read_parquet(curated / "advisories.parquet")
    obs = pd.read_parquet(curated / "observations.parquet") if (curated / "observations.parquet").exists() else pd.DataFrame()
    latest_env_path = curated / "latest_env.parquet"
    latest_env = pd.read_parquet(latest_env_path) if latest_env_path.exists() else pd.DataFrame()

    fc_by_bid = {row["beach_id"]: row for _, row in forecasts.iterrows()}
    env_by_bid = {row["beach_id"]: row for _, row in latest_env.iterrows()}

    if not obs.empty:
        obs["sample_time"] = pd.to_datetime(obs["sample_time"], errors="coerce")
        latest_sample = obs.dropna(subset=["sample_time"]).groupby("beach_id")["sample_time"].max()
    else:
        latest_sample = pd.Series(dtype="datetime64[ns]")

    active_bids, website_map = _active_advisory_set(advisories)

    # Loaded here rather than in the parent section below because the per-station
    # rows are dumped to beaches.json first and need the sibling rollup.
    parents_path = curated / "parent_beaches.parquet"
    parent_df = pd.read_parquet(parents_path) if parents_path.exists() else pd.DataFrame()
    siblings_by_station = _sibling_map(parent_df)

    out.mkdir(parents=True, exist_ok=True)

    # beaches.json — per-station entries
    beach_rows = []
    for _, b in beaches.iterrows():
        bid = str(b["beach_id"])
        has_adv = bid in active_bids
        # Beach-wide rollup, only meaningful when this station is NOT itself
        # posted (a posted station already shows its own advisory). Mirrors
        # `serving_repository._parent_advisory_signal`.
        parent_has_adv = False
        parent_adv_url = None
        if not has_adv:
            for sibling_id in siblings_by_station.get(bid, ()):
                if sibling_id != bid and sibling_id in active_bids:
                    parent_has_adv = True
                    parent_adv_url = parent_adv_url or website_map.get(sibling_id)
                    if parent_adv_url:
                        break
        forecast_block = None
        env_block = None
        if bid in fc_by_bid:
            forecast_block = _build_forecast_block(
                fc_by_bid[bid], has_adv, parent_has_adv, parent_adv_url
            )
        if bid in env_by_bid:
            env_block = {k: _safe(v) for k, v in env_by_bid[bid].items() if k != "beach_id"}

        # Prefer the friendly local `name` (e.g. "Black's Beach" for the
        # FM-090 station under "Torrey Pines State Beach") so app search
        # can match the name users actually know stations by. Fall back to
        # station_code only if no friendly name is set.
        local_name_raw = str(b.get("name") or "")
        local_name = local_name_raw.replace("\\'", "'").replace("\\\\", "")
        station_code = str(b.get("station_code") or "")
        station_name = local_name or station_code or str(b.get("beach_name") or "")
        beach_name = str(b.get("beach_name") or "")
        display_name = beach_name or local_name
        if station_name and station_name != display_name:
            display_name = f"{display_name} ({station_name})" if display_name else station_name

        # water_body_type drives the surf-spot classification in the web's
        # coverage stats. "Open Coast" → surf-relevant. "Sound, Bay, or
        # Inlet" / "Lake/Reservoir" / "Stream/Creek" → bay-or-inland.
        beach_rows.append({
            "id": bid,
            "name": display_name,
            "station_name": station_name,
            "station_code": station_code or None,
            "county": _safe(b.get("county")),
            "region": _safe(b.get("region")),
            "latitude": _safe(b.get("latitude")),
            "longitude": _safe(b.get("longitude")),
            "support_status": _safe(b.get("support_status")) or "unsupported",
            "water_body_type": _safe(b.get("water_body_type")),
            "latest_official_sample_at": _safe(latest_sample.get(bid)) if not latest_sample.empty else None,
            "has_active_advisory": has_adv,
            "advisory_website": website_map.get(bid),
            "parent_has_active_advisory": parent_has_adv,
            "parent_advisory_website": parent_adv_url,
            "forecast": forecast_block,
            "env": env_block,
        })

    with (out / "beaches.json").open("w") as f:
        json.dump(beach_rows, f, separators=(",", ":"), default=str)
    print(f"  beaches.json: {len(beach_rows)} stations, "
          f"{sum(1 for r in beach_rows if r['has_active_advisory'])} with active advisory",
          file=sys.stderr)

    # parent_beaches.json — the authoritative parent grouping (ids + membership)
    # comes from the curated parent_beaches.parquet, which is the EXACT source the
    # live API serves from (see app.repositories.serving_repository). Re-deriving
    # parent ids here from the leading beach_id segment used to DIVERGE from the
    # API's geographic sub-cluster split: derive_parent_beaches DBSCAN-splits any
    # usepa_id group spanning >5 km into directional parents (e.g. "La Jolla Shores
    # Beach · North" -> parent-ca876094-1 / "· South" -> parent-ca876094-2), while
    # this script collapsed all of them into a single parent-ca876094. The static
    # site's generateStaticParams baked only the collapsed id, so every split
    # parent the directory's live API refresh linked to (parent-ca876094-1, -2)
    # 404'd. Reading the parquet keeps the baked ids — and therefore the prebuilt
    # /parent/<id> pages — in lockstep with the API feed. The per-station roll-up
    # fields the web expects (member names/codes, advisory, worst risk band) are
    # aggregated here from beach_rows.
    beach_by_id = {r["id"]: r for r in beach_rows}
    # No "Advisory" entry: it is no longer a band value. A parent's advisory state
    # rides on has_active_advisory (OR across members, deliberate), while the band
    # is the worst MODEL band among members. "Advisory" is kept mapping to the top
    # only so a stale row baked by an older pipeline still sorts sanely.
    order = {"Low": 1, "Moderate": 2, "High": 3, "Very High": 4, "Advisory": 5}

    parent_rows = []
    if parents_path.exists():
        for _, pr in parent_df.iterrows():
            member_ids = _member_ids(pr.get("member_beach_ids"))
            members = [beach_by_id[mid] for mid in member_ids if mid in beach_by_id]

            has_adv = any(m["has_active_advisory"] for m in members)
            advisory_website = next(
                (m["advisory_website"] for m in members
                 if m["has_active_advisory"] and m["advisory_website"]),
                None,
            )

            # Worst-band aggregation; Advisory outranks every model band.
            band_priority, risk_band_val, p_exceed_val = -1, None, None
            for m in members:
                fc = m["forecast"] or {}
                band = fc.get("risk_band")
                pri = order.get(band, 0)
                if pri > band_priority:
                    band_priority = pri
                    risk_band_val = band
                    p_exceed_val = fc.get("p_exceed")

            # Latest official sample across members (obs-derived, matching
            # beaches.json), falling back to the parquet's own value.
            latest = None
            for m in members:
                last = m["latest_official_sample_at"]
                if last and (latest is None or last > latest):
                    latest = last
            if latest is None:
                latest = _safe(pr.get("latest_official_sample_at"))

            parent_rows.append({
                "id": str(pr["parent_beach_id"]),
                "name": str(pr["name"]),
                "county": _safe(pr.get("county")),
                "region": _safe(pr.get("region")),
                "support_status": _safe(pr.get("support_status")) or "unsupported",
                "station_count": (
                    int(pr["station_count"]) if pd.notna(pr.get("station_count"))
                    else len(member_ids)
                ),
                "member_beach_ids": member_ids,
                "member_beach_names": [
                    (beach_by_id[mid]["station_name"] or beach_by_id[mid]["name"])
                    if mid in beach_by_id else mid
                    for mid in member_ids
                ],
                "member_station_codes": [
                    (beach_by_id[mid]["station_code"] or "") if mid in beach_by_id else ""
                    for mid in member_ids
                ],
                "latest_official_sample_at": latest,
                "latitude": _safe(pr.get("latitude")),
                "longitude": _safe(pr.get("longitude")),
                "has_active_advisory": has_adv,
                "advisory_website": advisory_website,
                "risk_band": risk_band_val,
                "p_exceed": p_exceed_val,
            })
        print(f"  parent_beaches.json: {len(parent_rows)} parents "
              f"(from parent_beaches.parquet)", file=sys.stderr)
    else:
        # Legacy fallback — keep the bake alive if the parquet is unavailable,
        # but warn loudly: this path re-derives parent ids by beach_id prefix
        # and CANNOT reproduce the API's geographic split, so split-parent
        # pages will 404. Deploy should always supply parent_beaches.parquet.
        print("::warning::parent_beaches.parquet missing — falling back to "
              "prefix grouping; split-parent ids will NOT match the API",
              file=sys.stderr)
        parents: dict[str, dict] = {}
        for r in beach_rows:
            parent_key = "parent-" + r["id"].split("-")[0]
            p = parents.setdefault(parent_key, {
                "id": parent_key,
                "name": r["name"].rsplit(" (", 1)[0],
                "county": r["county"],
                "region": r["region"],
                "support_status": r["support_status"],
                "station_count": 0,
                "member_beach_ids": [],
                "member_beach_names": [],
                "member_station_codes": [],
                "latest_official_sample_at": None,
                "latitude": r["latitude"],
                "longitude": r["longitude"],
                "has_active_advisory": False,
                "advisory_website": None,
                "risk_band": None,
                "p_exceed": None,
                "_band_priority": -1,
            })
            p["station_count"] += 1
            p["member_beach_ids"].append(r["id"])
            p["member_beach_names"].append(r["station_name"] or r["name"])
            p["member_station_codes"].append(r["station_code"] or "")
            if r["has_active_advisory"]:
                p["has_active_advisory"] = True
                p["advisory_website"] = p["advisory_website"] or r["advisory_website"]
            last = r["latest_official_sample_at"]
            if last and (p["latest_official_sample_at"] is None or last > p["latest_official_sample_at"]):
                p["latest_official_sample_at"] = last

            fc = r["forecast"] or {}
            band = fc.get("risk_band")
            pri = order.get(band, 0)
            if pri > p["_band_priority"]:
                p["_band_priority"] = pri
                p["risk_band"] = band
                p["p_exceed"] = fc.get("p_exceed")

        for p in parents.values():
            p.pop("_band_priority", None)
            parent_rows.append(p)
        print(f"  parent_beaches.json: {len(parent_rows)} parents "
              f"(LEGACY prefix grouping)", file=sys.stderr)

    with (out / "parent_beaches.json").open("w") as f:
        json.dump(parent_rows, f, separators=(",", ":"), default=str)

    # regional_summary.json — counts by region
    region_summary: dict[str, dict] = {}
    for r in beach_rows:
        reg = r["region"] or "Unknown"
        s = region_summary.setdefault(reg, {
            "region": reg, "stations_total": 0, "stations_active_advisory": 0,
            "stations_modeled": 0,
        })
        s["stations_total"] += 1
        if r["has_active_advisory"]:
            s["stations_active_advisory"] += 1
        if r["forecast"]:
            s["stations_modeled"] += 1
    with (out / "regional_summary.json").open("w") as f:
        json.dump(list(region_summary.values()), f, separators=(",", ":"), default=str)
    print(f"  regional_summary.json: {len(region_summary)} regions", file=sys.stderr)

    if with_details:
        _bake_details(curated, out, beaches, parent_df, forecasts, advisories, obs, latest_env)


# --------------------------------------------------------------------------- #
# --with-details: health.json + beach/{id}.json (docs/STATIC_DATA_CONTRACT.md)
#
# Everything below is a standalone port of logic that lives in the `app`
# package, because this script is curl'd by shorelife-web's deploy and cannot
# import it. `tests/test_static_bake_parity.py` pins each port against the
# original: ADVISORY_AUTO_EXPIRE_DAYS, _CA_TIDE_STATIONS, derive_friendly_name,
# the explain template, and the payload shapes against the pydantic models.
# --------------------------------------------------------------------------- #

# Keep in lockstep with `app.data.pipeline.serving_snapshot.ADVISORY_AUTO_EXPIRE_DAYS`.
ADVISORY_AUTO_EXPIRE_DAYS = 14
OBSERVATION_LIMIT = 52  # contract: newest 52 samples, newest first
ADVISORY_LIMIT = 10  # serving_repository.get_observations
ENVIRONMENT_LIMIT = 10  # serving_snapshot.ENVIRONMENT_LIMIT
# tides.parquet carries >= 72 h ahead; the route's chart wants this much history.
TIDE_PAST_HOURS = 10

# Keep in lockstep with `app.services.tides.CA_TIDE_STATIONS`.
_CA_TIDE_STATIONS: tuple[tuple[str, str, float, float], ...] = (
    ("9419750", "Crescent City", 41.7456, -124.1844),
    ("9418767", "North Spit, Humboldt Bay", 40.7667, -124.2167),
    ("9418723", "North Jetty, Humboldt Bay", 40.7667, -124.2333),
    ("9416841", "Arena Cove", 38.9145, -123.7113),
    ("9415020", "Point Reyes", 37.9961, -122.9744),
    ("9414750", "Alameda", 37.7717, -122.3000),
    ("9414290", "San Francisco", 37.8063, -122.4659),
    ("9413450", "Monterey", 36.6050, -121.8881),
    ("9412110", "Port San Luis", 35.1686, -120.7542),
    ("9411406", "Oceano Beach Pier", 35.1011, -120.6300),
    ("9411340", "Santa Barbara", 34.4036, -119.6925),
    ("9411270", "Rincon Island, Mussel Shoals", 34.3500, -119.4400),
    ("9410840", "Santa Monica", 34.0083, -118.5000),
    ("9410660", "Los Angeles", 33.7200, -118.2728),
    ("9410680", "Long Beach Pier J", 33.7400, -118.1869),
    ("9410580", "Newport Bay Entrance", 33.6028, -117.8819),
    ("9410230", "La Jolla", 32.8669, -117.2571),
    ("9410170", "San Diego", 32.7142, -117.1736),
    ("9410079", "Mission Bay Entrance", 32.7800, -117.2533),
)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Vendored twin of app.core.geo.haversine_km (R = 6371.0)."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * 6371.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _nearest_tide_station(lat: float, lon: float) -> tuple[str, str, float]:
    """Vendored twin of app.services.tides.nearest_station."""
    best = ("", "", float("inf"))
    for sid, name, slat, slon in _CA_TIDE_STATIONS:
        d = _haversine_km(lat, lon, slat, slon)
        if d < best[2]:
            best = (sid, name, d)
    return best


def _derive_friendly_name(beach_id: str, county: str, station_name: str, beach_name: str = "") -> str:
    """Vendored twin of app.repositories._coerce.derive_friendly_name."""
    b_name = str(beach_name or "").strip()
    station_raw = str(station_name or "")
    if b_name:
        return b_name
    stem = re.sub(r"^ca\d+-", "", str(beach_id))
    county_slug = str(county or "").lower().replace(" ", "-")
    if county_slug and stem.startswith(county_slug + "-"):
        stem = stem[len(county_slug) + 1 :]
    station_slug = re.sub(r"[^a-z0-9]+", "-", station_raw.lower()).strip("-")
    if station_slug and stem.endswith("-" + station_slug):
        stem = stem[: -(len(station_slug) + 1)]
    b_name = stem.replace("-", " ").title() if stem else station_raw
    if (
        b_name
        and station_raw
        and b_name.lower() != station_raw.lower()
        and station_raw.lower() not in b_name.lower()
    ):
        return f"{b_name} ({station_raw})"
    return b_name or station_raw


def explain_summary(beach_name: str, risk_band_value: str, p_exceed: float, top_drivers: list[str]) -> str:
    """Vendored twin of the template in BeachService.explain_forecast."""
    drivers = top_drivers[:2]
    driver_line = (
        "Key factors: " + "; ".join(drivers) + "."
        if drivers
        else "No strong environmental signal detected."
    )
    return (
        f"{beach_name} is forecast at {risk_band_value.lower()} risk today. "
        f"The model estimates a {p_exceed:.0%} chance of exceeding the marine "
        f"enterococcus threshold. {driver_line} "
        "This is a model estimate, not an official advisory or lab result."
    )


def _clean(value):
    """JSON-safe scalar: NaN/NaT/inf/NA -> None, numpy scalars -> python."""
    if value is None:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _advisory_website(raw) -> str | None:
    """Vendored twin of app.repositories._coerce.coerce_advisory_website."""
    value = _clean(raw)
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "unknown":
        return None
    return text


def _expire_zombie_advisories(advisories: pd.DataFrame) -> pd.DataFrame:
    """Vendored twin of serving_snapshot.auto_expire_zombie_advisories (in memory)."""
    if advisories.empty or "status" not in advisories.columns:
        return advisories
    frame = advisories.copy()
    active = frame["status"] == "active"
    if not active.any():
        return frame
    advisory_type = frame.get("advisory_type", pd.Series("", index=frame.index))
    is_chronic = advisory_type.fillna("").str.contains("chronic", case=False, na=False)
    started = pd.to_datetime(frame.get("started_at"), errors="coerce", utc=True)
    if "last_seen_at" in frame.columns:
        reference = pd.to_datetime(frame["last_seen_at"], errors="coerce", utc=True).fillna(started)
    else:
        reference = started
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=ADVISORY_AUTO_EXPIRE_DAYS)
    frame.loc[active & reference.notna() & (reference < cutoff) & ~is_chronic, "status"] = "historical"
    return frame


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w") as f:
        json.dump(payload, f, separators=(",", ":"), default=str, allow_nan=False)
    os.replace(tmp, path)


def _health_payload(curated: Path, advisories: pd.DataFrame) -> dict:
    """The `SystemHealthResponse` payload, as the serving repository assembles it.

    ``system_health.json`` is ~12 KB, so nothing is trimmed: the research
    sections (served_metrics, serving_method, ...) ride along as extra keys that
    the model ignores and the web research page reads.
    """
    health_path = curated / "system_health.json"
    payload = json.loads(health_path.read_text()) if health_path.exists() else {}

    audit = None
    audit_path = curated / "advisory_audit.json"
    if audit_path.exists():
        try:
            raw = json.loads(audit_path.read_text())
            audit = {
                "generated_at": raw.get("generated_at"),
                "agreement_rate": raw.get("agreement_rate"),
                "false_negatives": (raw.get("false_negatives") or {}).get("count"),
                "false_positives": (raw.get("false_positives") or {}).get("count"),
                "active_advisories": raw.get("active_advisories"),
            }
        except (ValueError, AttributeError):
            audit = None

    active_count = int((advisories["status"] == "active").sum()) if "status" in advisories.columns else 0
    base = {
        "app_env": os.getenv("APP_ENV", "production"),
        "is_beta_product": True,
        "pipeline_freshness": "unknown",
        "source_freshness": {},
        "model_registry": {},
        "active_advisories_count": active_count,
        "forecast_audit": audit,
        "repository_mode": "static",
        "serving_snapshot": {"generated_at": datetime.now(timezone.utc).isoformat()},
    }
    return {**base, **payload}


def _observation_payloads(
    obs: pd.DataFrame, advisories: pd.DataFrame, beach_day: pd.DataFrame
) -> dict[str, dict]:
    """beach_id -> ObservationResponse payload (the route's JSON)."""
    out: dict[str, dict] = {}

    obs_by: dict[str, list[dict]] = {}
    if not obs.empty:
        # Same sort call as serving_snapshot._recent_by_beach (on the unfiltered
        # frame) so equal-timestamp rows keep the order the API serves them in.
        ordered = obs.sort_values(["beach_id", "sample_time"], ascending=[True, False])
        usable = ordered.dropna(subset=["beach_id", "sample_time", "analyte", "method", "units", "value"])
        usable = usable.groupby("beach_id", sort=False).head(OBSERVATION_LIMIT)
        # The route's `where beach_id=? order by sample_time desc` walks the
        # (beach_id, sample_time) index backwards, so equal timestamps come out
        # in REVERSE table order: reverse, then stable-sort newest first.
        usable = usable.iloc[::-1].sort_values("sample_time", ascending=False, kind="stable")
        for row in usable[
            ["beach_id", "sample_time", "analyte", "method", "units", "value", "exceeds_stv"]
        ].itertuples(index=False):
            obs_by.setdefault(str(row.beach_id), []).append({
                "sample_time": pd.Timestamp(row.sample_time).isoformat(),
                "analyte": str(row.analyte),
                "method": str(row.method),
                "units": str(row.units),
                "value": float(row.value),
                "exceeds_stv": bool(row.exceeds_stv),
            })

    adv_by: dict[str, list[dict]] = {}
    if not advisories.empty:
        # `advisories` is the advisories_recent frame (see _snapshot_advisories).
        adv = advisories.dropna(subset=["beach_id", "advisory_type", "started_at", "status"]).copy()
        adv["started_at"] = pd.to_datetime(adv["started_at"], errors="coerce")
        adv["ended_at"] = pd.to_datetime(adv["ended_at"], errors="coerce")
        # Same index-backwards tie order as the observations above.
        adv = adv.dropna(subset=["started_at"]).iloc[::-1].sort_values(
            "started_at", ascending=False, kind="stable")
        adv = adv.groupby("beach_id", sort=False).head(ADVISORY_LIMIT)
        for (bid, kind, started, ended, status), url in zip(
            adv[["beach_id", "advisory_type", "started_at", "ended_at", "status"]].itertuples(index=False, name=None),
            adv["advisory_website"],
        ):
            adv_by.setdefault(str(bid), []).append({
                "advisory_type": str(kind),
                "started_at": pd.Timestamp(started).isoformat(),
                "ended_at": None if pd.isna(ended) else pd.Timestamp(ended).isoformat(),
                "status": str(status),
                "advisory_website": _advisory_website(url),
            })

    env_by: dict[str, list[dict]] = {}
    if not beach_day.empty:
        day = beach_day.dropna(subset=["beach_id", "sample_date"]).copy()
        day["_d"] = pd.to_datetime(day["sample_date"], errors="coerce")
        day = day.dropna(subset=["_d"]).sort_values(["beach_id", "_d"], ascending=[True, False])
        day = day.groupby("beach_id", sort=False).head(ENVIRONMENT_LIMIT)
        for rec in day.to_dict("records"):
            env_by.setdefault(str(rec["beach_id"]), []).append({
                "date": str(rec["sample_date"])[:10],
                "wave_height_m": _finite_or_none(rec.get("wave_height_m")),
                "dominant_period_s": _finite_or_none(rec.get("dominant_period_s")),
                "water_temperature_c": _finite_or_none(rec.get("water_temperature_c")),
                "salinity_psu": _finite_or_none(rec.get("salinity_psu")),
                "weather": _clean(rec.get("weather")),
                "storm_drain_flow": _clean(rec.get("storm_drain_flow")),
                "tidal_height": _finite_or_none(rec.get("tidal_height")),
                "surf_height_observed": _finite_or_none(rec.get("surf_height_observed")),
                "turbidity_observed": _finite_or_none(rec.get("turbidity_observed")),
                "wind_speed_mps": _finite_or_none(rec.get("wind_speed_24h_max")),
                "wind_direction_deg": _finite_or_none(rec.get("wind_direction_24h_mean")),
                "uv_index": _finite_or_none(rec.get("uv_index_24h_max")),
            })

    for bid, observations in obs_by.items():
        out[bid] = {
            "beach_id": bid,
            "observations": observations,
            "advisories": adv_by.get(bid, []),
            "recent_environment": env_by.get(bid, []),
        }
    return out


_BEACH_DAY_COLUMNS = (
    "beach_id", "sample_date", "wave_height_m", "dominant_period_s", "water_temperature_c",
    "salinity_psu", "weather", "storm_drain_flow", "tidal_height", "surf_height_observed",
    "turbidity_observed", "wind_speed_24h_max", "wind_direction_24h_mean", "uv_index_24h_max",
)


def _read_beach_day(curated: Path) -> pd.DataFrame:
    path = curated / "beach_day.parquet"
    if not path.exists():
        return pd.DataFrame()
    import pyarrow.parquet as pq

    present = set(pq.read_schema(path).names)
    return pd.read_parquet(path, columns=[c for c in _BEACH_DAY_COLUMNS if c in present])


def _hourly_cells(curated: Path) -> dict[tuple[float, float], dict]:
    """(lat_r, lon_r) -> payload, as app.services.hourly_store reads it."""
    path = curated / "hourly_forecast.parquet"
    if not path.exists():
        return {}
    cells: dict[tuple[float, float], dict] = {}
    for row in pd.read_parquet(path).itertuples(index=False):
        try:
            cells[(round(float(row.lat_r), 1), round(float(row.lon_r), 1))] = json.loads(row.payload_json)
        except (ValueError, TypeError):
            continue
    return cells


def _tide_stations(curated: Path, now: datetime) -> dict[str, dict]:
    """station_id -> {station_name, predictions, extrema} from tides.parquet,
    in the route's shape, trimmed to start TIDE_PAST_HOURS before ``now``."""
    path = curated / "tides.parquet"
    if not path.exists():
        return {}
    frame = pd.read_parquet(path)
    if frame.empty:
        return {}
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame[frame["timestamp"] >= pd.Timestamp(now - timedelta(hours=TIDE_PAST_HOURS))]
    frame = frame.sort_values("timestamp")
    stations: dict[str, dict] = {}
    for sid, group in frame.groupby("station_id"):
        stamps = group["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        is_pred = group["kind"] == "prediction"
        predictions = [
            {"t": t, "v": float(v)} for t, v in zip(stamps[is_pred], group.loc[is_pred, "height"])
        ]
        extrema = [
            {"t": t, "type": str(k), "v": float(v)}
            for t, k, v in zip(stamps[~is_pred], group.loc[~is_pred, "type"], group.loc[~is_pred, "height"])
        ]
        if predictions:
            stations[str(sid)] = {"predictions": predictions, "extrema": extrema}
    return stations


# --------------------------------------------------------------------------- #
# API-shaped files (`api/*`): ports of ServingSnapshotRepository / BeachService,
# pinned against the originals by tests/test_static_bake_parity.py.
# --------------------------------------------------------------------------- #

MAX_FORECAST_AGE_HOURS = 48  # app.schemas.domain
_LOW_CONFIDENCE_RECENCY_BANDS = frozenset({"very_stale", "unknown"})  # app.ml.calibration
_INLAND_LAT, _INLAND_LON, _K_NEIGHBORS = 37.0, -120.5, 5  # app.services.shore_normal
_ENV_KEYS = (
    "wave_height_m", "dominant_period_s", "water_temperature_c", "salinity_psu",
    "uv_index", "wind_speed_mps", "wind_direction_deg",
)


def _sf(value) -> float | None:
    """Twin of app.repositories._coerce.safe_float."""
    try:
        if value is None:
            return None
        parsed = float(value)
        return None if math.isnan(parsed) else parsed
    except (TypeError, ValueError):
        return None


def _si(value) -> int | None:
    number = _sf(value)
    return int(number) if number is not None else None


def _sb(value, default: bool = True) -> bool:
    """Twin of app.repositories._coerce.safe_bool."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        return value.lower() not in ("0", "false", "no", "")
    return default


def _parse_dt(value) -> datetime | None:
    value = _clean(value)
    if value is None or value == "":
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _dt_text(value) -> str | None:
    parsed = _parse_dt(value)
    return parsed.isoformat() if parsed is not None else None


def _stored_text(value) -> str:
    """How the value reads back out of serving.sqlite (datetimes become ISO text)."""
    value = _clean(value)
    if isinstance(value, (pd.Timestamp, datetime)) or hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_list(value) -> list[str]:
    """Twin of serving_snapshot._json_dumps + serving_repository._parse_json_list."""
    if value is None:
        return []
    if isinstance(value, float) and math.isnan(value):
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return [str(v) for v in value] if isinstance(value, list) else []


def _sample_recency_band(age: int | None) -> str:
    """Twin of app.schemas.domain.sample_recency_band."""
    if age is None:
        return "unknown"
    if age <= 3:
        return "fresh"
    if age <= 20:
        return "recent"
    if age <= 60:
        return "stale"
    return "very_stale"


def _serve_time_band(
    raw: float | None, stored: float | None, *, active_advisory: bool, recency_band: str | None
) -> tuple[str, float]:
    """Twin of serving_repository.serve_time_band (+ confidence_capped_risk_band)."""
    base = raw if raw is not None else stored
    if base is None:
        return "Low", 0.0
    if active_advisory:
        band_p, _ = advisory_floored_probability(float(base), True)
        served_p, _ = advisory_floored_probability(float(stored if stored is not None else base), True)
        return risk_band(band_p), float(served_p)
    band = risk_band(float(base))
    if band in ("High", "Very High") and recency_band in _LOW_CONFIDENCE_RECENCY_BANDS:
        band = "Moderate"
    return band, float(base)


def _shore_normal_deg(beach_id: str, population: list[tuple[str, float, float]]) -> float | None:
    """Twin of app.services.shore_normal.compute_shore_normal_deg."""
    import numpy as np

    ids, lats, lons, target = [], [], [], None
    for bid, lat, lon in population:
        try:
            lat_f, lon_f = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(lat_f) and np.isfinite(lon_f)):
            continue
        ids.append(bid)
        lats.append(lat_f)
        lons.append(lon_f)
        if bid == beach_id:
            target = (lat_f, lon_f)
    if target is None or len(ids) < 2:
        return None
    lat_arr, lon_arr = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
    tlat, tlon = target
    order = np.argsort((lat_arr - tlat) ** 2 + (lon_arr - tlon) ** 2)
    idx = [i for i in order if ids[i] != beach_id][:_K_NEIGHBORS]
    if len(idx) < 2:
        return None
    lat_scale = 110_540.0
    lon_scale = 111_320.0 * np.cos(np.deg2rad(tlat))
    xy = np.column_stack([(lon_arr[idx] - tlon) * lon_scale, (lat_arr[idx] - tlat) * lat_scale])
    xy = xy - xy.mean(axis=0)
    try:
        _, _, vt = np.linalg.svd(xy, full_matrices=False)
    except np.linalg.LinAlgError:
        return 270.0
    tangent = vt[0]
    n_a = np.array([-tangent[1], tangent[0]])
    inland = np.array([(_INLAND_LON - tlon) * lon_scale, (_INLAND_LAT - tlat) * lat_scale])
    seaward = n_a if np.dot(n_a, inland) < 0 else -n_a
    return float((np.rad2deg(np.arctan2(seaward[0], seaward[1])) + 360.0) % 360.0)


_ADVISORY_COLUMNS = (
    "beach_id", "advisory_type", "started_at", "ended_at", "status", "cause", "county", "advisory_website",
)


def _filter_currently_active(frame: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Twin of curated_repository.filter_currently_active."""
    if frame.empty or "status" not in frame.columns:
        return frame.iloc[0:0]
    active = frame.loc[frame["status"] == "active"].copy()
    if active.empty:
        return active
    stamp = pd.Timestamp(now)
    if "ended_at" in active.columns:
        ended = pd.to_datetime(active["ended_at"], errors="coerce", utc=True)
        active = active.loc[~(ended.notna() & (ended <= stamp))]
        if active.empty:
            return active
    started = pd.to_datetime(active["started_at"], errors="coerce", utc=True)
    kind = active["advisory_type"] if "advisory_type" in active.columns else pd.Series("", index=active.index)
    is_closure = kind.fillna("").str.contains("closure", case=False, na=False)
    return active.loc[is_closure | (started >= stamp - pd.Timedelta(days=ACTIVE_WINDOW_DAYS))]


def _snapshot_advisories(advisories: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """The `advisories_recent` table, row for row: twin of
    serving_snapshot._recent_advisories. Its row order matters, because the API
    breaks `order by started_at desc` ties by rowid."""
    if advisories.empty:
        return pd.DataFrame(columns=list(_ADVISORY_COLUMNS))
    recent = advisories.copy()
    for column in _ADVISORY_COLUMNS:
        if column not in recent.columns:
            recent[column] = None
    recent["started_at"] = pd.to_datetime(recent["started_at"], errors="coerce")
    recent = recent.sort_values(["beach_id", "started_at"], ascending=[True, False])
    latest = recent.groupby("beach_id", as_index=False, group_keys=False).head(10)
    active = _filter_currently_active(recent, now)
    return pd.concat([latest, active], ignore_index=True).drop_duplicates()[list(_ADVISORY_COLUMNS)]


def _api_active_advisories(
    snapshot: pd.DataFrame, now: datetime
) -> tuple[set[str], dict[str, str | None]]:
    """(active beach ids, beach_id -> most recent active URL) as the serving
    repository computes them over `advisories_recent`: status 'active', not
    lifted, and closure or started within ACTIVE_WINDOW_DAYS. The URL is the
    first row by started_at desc (ties: table order) and is NOT skipped past
    when it is blank."""
    if snapshot.empty or "status" not in snapshot.columns:
        return set(), {}
    a = snapshot[snapshot["status"] == "active"]
    started = pd.to_datetime(a["started_at"], errors="coerce", utc=True)
    keep = pd.Series(True, index=a.index)
    ended = pd.to_datetime(a["ended_at"], errors="coerce", utc=True)
    keep &= ~(ended.notna() & (ended <= pd.Timestamp(now)))
    is_closure = a["advisory_type"].fillna("").str.contains("closure", case=False, na=False)
    keep &= is_closure | (started >= pd.Timestamp(now - timedelta(days=ACTIVE_WINDOW_DAYS)))
    a = a[keep].assign(_s=started[keep]).sort_values("_s", ascending=False, na_position="last", kind="stable")
    websites: dict[str, str | None] = {}
    for bid, url in zip(a["beach_id"], a["advisory_website"]):
        if str(bid) not in websites:
            websites[str(bid)] = _advisory_website(url)
    return set(websites), websites


def _beach_wide_map(
    parent_df: pd.DataFrame, active: set[str], websites: dict[str, str | None]
) -> dict[str, str | None]:
    """Twin of serving_repository._beach_wide_advisory_map."""
    if not active:
        return {}
    members_by_station: dict[str, tuple[str, ...]] = {}
    if not parent_df.empty and "member_beach_ids" in parent_df.columns:
        for raw in parent_df["member_beach_ids"]:
            members = tuple(_member_ids(raw))
            for bid in members:
                members_by_station[bid] = members
    result: dict[str, str | None] = {}
    for bid, members in members_by_station.items():
        if bid in active:
            continue
        for sibling in members:
            if sibling != bid and sibling in active:
                result[bid] = websites.get(sibling)
                break
    return result


def _clean_nickname(raw) -> str:
    return str(raw or "").strip().replace("\\'", "'").replace("\\\\", "")


def _api_beach_rows(
    beaches: pd.DataFrame,
    parent_df: pd.DataFrame,
    forecasts: pd.DataFrame,
    rollup: dict[str, str | None],
) -> list[dict]:
    """`BeachSummary` rows exactly as `BeachService.list_beaches()` returns them."""
    parent_name: dict[str, str] = {}
    if not parent_df.empty and "member_beach_ids" in parent_df.columns:
        for _, pr in parent_df.iterrows():
            name = str(_clean(pr.get("name")) or "").strip()
            if name:
                for mid in _member_ids(pr.get("member_beach_ids")):
                    parent_name.setdefault(mid, name)
    model_by_beach = (
        {str(b): str(m) for b, m in zip(forecasts["beach_id"], forecasts["model_version"])}
        if not forecasts.empty
        else {}
    )
    population = []
    for bid, lat, lon in zip(beaches["beach_id"], beaches["latitude"], beaches["longitude"]):
        try:
            population.append((str(bid), float(lat), float(lon)))
        except (TypeError, ValueError):
            continue
    rows = []
    for rec in beaches.to_dict("records"):
        r = {k: _clean(v) for k, v in rec.items()}
        bid = str(r["beach_id"])
        support = str(r["support_status"]) if r.get("support_status") else "unsupported"
        friendly = _derive_friendly_name(
            bid, str(r.get("county") or ""), str(r.get("name") or ""),
            str(r.get("beach_name") or "") if "beach_name" in r else "",
        )
        beach_name = None
        if r.get("beach_name") is not None:
            beach_name = str(r["beach_name"]).strip().replace("\\'", "'").replace("\\\\", "") or None
        code = r.get("station_code")
        rows.append({
            "id": bid,
            "name": parent_name.get(bid) or friendly,
            "station_name": _clean_nickname(r.get("name")) or None,
            "beach_name": beach_name,
            "station_code": (str(code).strip() or None) if code is not None else None,
            "county": str(r["county"]),
            "region": str(r["region"]),
            "support_status": support,
            "model_version": model_by_beach.get(bid),
            "latest_official_sample_at": _dt_text(r.get("latest_official_sample_at")),
            "geometry": {"latitude": float(r["latitude"]), "longitude": float(r["longitude"])},
            "shore_normal_deg": _shore_normal_deg(bid, population),
            "parent_has_active_advisory": bid in rollup,
            "parent_advisory_website": rollup.get(bid),
        })
    return sorted(rows, key=lambda x: (x["county"], x["name"]))


def _api_forecast_records(
    forecasts: pd.DataFrame,
    beaches: pd.DataFrame,
    latest_env: pd.DataFrame,
    active: set[str],
    websites: dict[str, str | None],
    rollup: dict[str, str | None],
    forecast_date: str,
    now: datetime,
) -> dict[str, dict]:
    """beach_id -> `ForecastRecord` as `get_forecast(beach_id, forecast_date)` returns it
    from a forecasts row (beaches with no row at all are absent: the API would derive
    or 404 there)."""
    rows_by: dict[str, list[dict]] = {}
    for rec in forecasts.to_dict("records"):
        drivers = _json_list(rec.get("top_drivers"))
        r = {k: _clean(v) for k, v in rec.items() if k != "top_drivers"}
        r["top_drivers"] = drivers
        rows_by.setdefault(str(r["beach_id"]), []).append(r)
    env_by: dict[str, dict] = {}
    for rec in latest_env.to_dict("records"):
        env_by.setdefault(str(rec["beach_id"]), {
            k: _sf(rec.get(k)) for k in _ENV_KEYS if k in rec
        })
    sample_at = {
        str(b): _clean(v)
        for b, v in zip(beaches["beach_id"], beaches["latest_official_sample_at"])
    } if "latest_official_sample_at" in beaches.columns else {}

    out: dict[str, dict] = {}
    for bid, rows in rows_by.items():
        exact = [r for r in rows if _stored_text(r.get("forecast_date")) == forecast_date]
        is_fallback = not exact
        row = exact[0] if exact else max(rows, key=lambda r: _stored_text(r.get("forecast_date")))
        env_fallback = env_by.get(bid, {})

        def pick(key, row=row, env_fallback=env_fallback):
            primary = _sf(row.get(key))
            return primary if primary is not None else env_fallback.get(key)

        gen_at = _parse_dt(row.get("forecast_generated_at"))
        age_hours = None
        age_exact = None
        if gen_at is not None:
            if gen_at.tzinfo is None:
                gen_at = gen_at.replace(tzinfo=timezone.utc)
            age_exact = max(0.0, (now - gen_at).total_seconds() / 3600)
            age_hours = int(age_exact)
        staleness = age_exact
        if staleness is None:
            try:
                d = date.fromisoformat(str(row.get("forecast_date"))[:10])
                staleness = max(
                    0.0, (now - datetime(d.year, d.month, d.day, tzinfo=timezone.utc)).total_seconds() / 3600
                )
            except (TypeError, ValueError):
                staleness = None
        is_stale = (
            staleness is None or staleness > MAX_FORECAST_AGE_HOURS or (age_hours is None and is_fallback)
        )

        raw_p = _sf(row.get("p_exceed_raw"))
        model_band = risk_band(raw_p) if raw_p is not None else str(row["risk_band"])
        sample_age = _si(row.get("sample_age_days"))
        if sample_age is None:
            try:
                s_dt = _parse_dt(sample_at.get(bid))
                f_dt = _parse_dt(_stored_text(row.get("forecast_date")))
                sample_age = (
                    None if s_dt is None or f_dt is None else max(0, (f_dt.date() - s_dt.date()).days)
                )
            except (ValueError, TypeError):
                sample_age = None
        active_advisory = bid in active
        band, served_p = _serve_time_band(
            raw_p, _sf(row.get("p_exceed")),
            active_advisory=active_advisory, recency_band=_sample_recency_band(sample_age),
        )
        floor_here = active_advisory and served_p > (raw_p or 0.0)
        drivers = list(row["top_drivers"])
        advisory_website = None
        parent_adv, parent_url = False, None
        if active_advisory:
            drivers = [OFFICIAL_ADVISORY_DRIVER, *drivers][:5]
            advisory_website = websites.get(bid)
        elif bid in rollup:
            parent_adv, parent_url = True, rollup[bid]
        out[bid] = {
            "beach_id": bid,
            "forecast_date": str(row.get("forecast_date"))[:10],
            "risk_band": band,
            "model_risk_band": model_band if active_advisory else None,
            "p_exceed": served_p,
            "p_exceed_raw": raw_p,
            "p_exceed_lower": _sf(row.get("p_exceed_lower")),
            "p_exceed_upper": _sf(row.get("p_exceed_upper")),
            "predicted_log_enterococcus": _sf(row.get("predicted_log_enterococcus")),
            "lower_prediction_interval": _sf(row.get("lower_prediction_interval")),
            "upper_prediction_interval": _sf(row.get("upper_prediction_interval")),
            "prediction_interval_level": _sf(row.get("prediction_interval_level")),
            "top_drivers": drivers,
            "model_version": str(row["model_version"]),
            "forecast_generated_at": gen_at.isoformat() if gen_at is not None else None,
            "forecast_age_hours": age_hours,
            "is_stale": is_stale,
            "official_advisory_active": active_advisory,
            "advisory_floor_applied": _sb(row.get("advisory_floor_applied"), default=False) or floor_here,
            "advisory_website": advisory_website,
            "parent_has_active_advisory": parent_adv,
            "parent_advisory_website": parent_url,
            "forecast_label_mode": (
                "official_advisory_override" if active_advisory else str(row.get("forecast_label_mode") or "model")
            ),
            "sample_age_days": sample_age,
            "sample_recency_band": str(row.get("sample_recency_band") or _sample_recency_band(sample_age)),
            "is_beta_forecast": _sb(row.get("is_beta_forecast"), default=True),
            "environmental_summary": {k: pick(k) for k in _ENV_KEYS},
        }
    return out


def _api_parent_rows(
    parent_df: pd.DataFrame,
    beaches: pd.DataFrame,
    forecasts: pd.DataFrame,
    active: set[str],
    websites: dict[str, str | None],
    forecast_records_by_row: dict[str, tuple[str, float, str]],
) -> list[dict]:
    """`ParentBeachSummary` rows exactly as `BeachService.list_parent_beaches()` returns them."""
    if parent_df.empty:
        return []
    names = {str(b): _clean_nickname(n) for b, n in zip(beaches["beach_id"], beaches["name"])}
    codes = {}
    if "station_code" in beaches.columns:
        for b, c in zip(beaches["beach_id"], beaches["station_code"]):
            c = _clean(c)
            codes[str(b)] = str(c).strip() if c is not None else ""
    flagged_display = dict(names)
    if "station_name" in beaches.columns:
        flagged_display = {}
        for b, n, sn in zip(beaches["beach_id"], beaches["name"], beaches["station_name"]):
            display = _clean_nickname(_clean(sn)) or _clean_nickname(n)
            if display:
                flagged_display[str(b)] = display
    rows = []
    for rec in parent_df.to_dict("records"):
        r = {k: _clean(v) if k != "member_beach_ids" else v for k, v in rec.items()}
        member_ids = _member_ids(r.get("member_beach_ids"))
        member_forecasts = [forecast_records_by_row[b] for b in member_ids if b in forecast_records_by_row]
        worst_band = worst_p = worst_model = None
        if member_forecasts:
            worst_band, worst_p, worst_model = max(member_forecasts, key=lambda item: item[1])
        flagged = [b for b in dict.fromkeys(member_ids) if b in active]
        website = next((websites[b] for b in flagged if websites.get(b)), None)
        rows.append({
            "id": str(r["parent_beach_id"]),
            "name": str(r["name"]),
            "county": str(r["county"]),
            "region": str(r["region"]),
            "support_status": str(r["support_status"]) if r.get("support_status") else "unsupported",
            "model_version": worst_model,
            "station_count": int(r["station_count"]),
            "member_beach_ids": member_ids,
            "member_beach_names": [n for n in (names.get(b, "") for b in member_ids) if n],
            "member_station_codes": [codes.get(b, "") for b in member_ids],
            "latest_official_sample_at": _dt_text(r.get("latest_official_sample_at")),
            "geometry": {"latitude": float(r["latitude"]), "longitude": float(r["longitude"])},
            "risk_band": worst_band,
            "p_exceed": worst_p,
            "has_active_advisory": bool(flagged),
            "advisory_website": website if flagged else None,
            "flagged_station_count": len(flagged),
            "flagged_station_names": [flagged_display[b] for b in flagged if b in flagged_display],
        })
    return sorted(rows, key=lambda x: (x["county"], x["name"]))


def _parent_forecast_lookup(
    forecasts: pd.DataFrame, active: set[str]
) -> dict[str, tuple[str, float, str]]:
    """beach_id -> (band, p, model_version), as list_parent_beaches derives it
    from every forecasts row (last row per beach wins)."""
    lookup: dict[str, tuple[str, float, str]] = {}
    for rec in forecasts.to_dict("records"):
        r = {k: _clean(v) for k, v in rec.items() if k != "top_drivers"}
        bid = str(r["beach_id"])
        band, p = _serve_time_band(
            _sf(r.get("p_exceed_raw")), _sf(r.get("p_exceed")),
            active_advisory=bid in active,
            recency_band=str(r.get("sample_recency_band") or "") or None,
        )
        lookup[bid] = (band, p, str(r["model_version"]))
    return lookup


def _bake_details(
    curated: Path,
    out: Path,
    beaches: pd.DataFrame,
    parent_df: pd.DataFrame,
    forecasts: pd.DataFrame,
    advisories: pd.DataFrame,
    obs: pd.DataFrame,
    latest_env: pd.DataFrame,
) -> None:
    """Write `api/*` (docs/STATIC_DATA_CONTRACT.md): the API's own payloads."""
    now = datetime.now(timezone.utc)
    advisories = _expire_zombie_advisories(advisories)
    api = out / "api"

    _write_json(api / "health.json", _health_payload(curated, advisories))
    print("  api/health.json written", file=sys.stderr)

    forecast_date = (
        str(pd.to_datetime(forecasts["forecast_date"]).max().date())
        if not forecasts.empty and "forecast_date" in forecasts.columns
        else now.date().isoformat()
    )
    snapshot_advisories = _snapshot_advisories(advisories, now)
    active, websites = _api_active_advisories(snapshot_advisories, now)
    rollup = _beach_wide_map(parent_df, active, websites)

    beach_rows = _api_beach_rows(beaches, parent_df, forecasts, rollup)
    records = _api_forecast_records(
        forecasts, beaches, latest_env, active, websites, rollup, forecast_date, now
    )
    parents = _api_parent_rows(
        parent_df, beaches, forecasts, active, websites, _parent_forecast_lookup(forecasts, active)
    )
    _write_json(api / "parent_beaches.json", parents)
    _write_json(api / "beaches.json", [{**row, "forecast": records.get(row["id"])} for row in beach_rows])
    print(f"  api/parent_beaches.json: {len(parents)}; api/beaches.json: {len(beach_rows)}", file=sys.stderr)

    observation_payloads = _observation_payloads(obs, snapshot_advisories, _read_beach_day(curated))
    hourly = _hourly_cells(curated)
    tide_stations = _tide_stations(curated, now)

    counts = {"observations": 0, "explain": 0, "hourly": 0, "tides": 0}
    for row in beach_rows:
        bid = row["id"]
        record = records.get(bid)
        explain = None
        if record is not None:
            explain = {
                "beach_id": bid,
                "summary": explain_summary(
                    row["name"], record["risk_band"], record["p_exceed"], record["top_drivers"]
                ),
                "used_model": "template-v1",
            }

        hourly_payload = None
        tides_payload = None
        lat, lon = row["geometry"]["latitude"], row["geometry"]["longitude"]
        cell = hourly.get((round(lat, 1), round(lon, 1)))
        if cell is not None:
            hourly_payload = {"beach_id": bid, **cell}
        sid, sname, dist = _nearest_tide_station(lat, lon)
        station = tide_stations.get(sid)
        if station is not None:
            tides_payload = {
                "beach_id": bid,
                "station_id": sid,
                "station_name": sname,
                "station_distance_km": round(dist, 2),
                "predictions": station["predictions"],
                "extrema": station["extrema"],
            }

        observations = observation_payloads.get(bid)
        counts["observations"] += observations is not None
        counts["explain"] += explain is not None
        counts["hourly"] += hourly_payload is not None
        counts["tides"] += tides_payload is not None
        _write_json(api / "beach" / f"{bid}.json", {
            "beach_id": bid,
            "forecast_date": forecast_date,
            "generated_at": now.isoformat(),
            "observations": observations,
            "explain": explain,
            "hourly": hourly_payload,
            "tides": tides_payload,
        })
    print(f"  api/beach/*.json: {len(beach_rows)} files; sections present: {counts}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--curated", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--with-details",
        action="store_true",
        help="Also write the API-shaped api/* files (parent_beaches, beaches with "
             "forecast, health, beach/{id}) per docs/STATIC_DATA_CONTRACT.md.",
    )
    args = parser.parse_args()
    bake(args.curated, args.out, with_details=args.with_details)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
