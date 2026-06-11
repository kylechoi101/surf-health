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
import sys
from datetime import datetime, timedelta, timezone
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


OFFICIAL_ADVISORY_DRIVER = "Official health advisory is active for this station."
ACTIVE_WINDOW_DAYS = 14  # Match serving_repository's 14-day acute window


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

    Mirrors `serving_repository._active_advisory_beach_ids` semantics: status='active'
    AND started_at within the last 14 days. Counties don't reliably log closures,
    so the 14-day window prevents zombie advisories from hanging forever.
    """
    if advisories.empty:
        return set(), {}
    a = advisories.copy()
    a["started_at"] = pd.to_datetime(a["started_at"], errors="coerce")
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=ACTIVE_WINDOW_DAYS)
    is_active = a["status"] == "active"
    # Closures bypass the 14d acute window — they describe ongoing hazards
    # (Tijuana Slough since Oct 2025, etc.) and persist until the scraper
    # stops seeing them. Postings still get the 14d gate.
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


def _build_forecast_block(fc_row: pd.Series, has_active_advisory: bool) -> dict:
    """Mirror curated_repository.get_forecast's override logic."""
    row = {k: _safe(v) for k, v in fc_row.items()}
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
        row["official_advisory_active"] = True
        row["model_risk_band"] = model_band
        row["risk_band"] = "Advisory"
        row["forecast_label_mode"] = "official_advisory_override"
        drivers = list(row.get("top_drivers") or [])
        drivers = [d for d in drivers if d != OFFICIAL_ADVISORY_DRIVER]
        row["top_drivers"] = [OFFICIAL_ADVISORY_DRIVER, *drivers][:5]
    else:
        row["official_advisory_active"] = False
        row["model_risk_band"] = None
    return row


def bake(curated: Path, out: Path) -> None:
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

    out.mkdir(parents=True, exist_ok=True)

    # beaches.json — per-station entries
    beach_rows = []
    for _, b in beaches.iterrows():
        bid = str(b["beach_id"])
        has_adv = bid in active_bids
        forecast_block = None
        env_block = None
        if bid in fc_by_bid:
            forecast_block = _build_forecast_block(fc_by_bid[bid], has_adv)
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
            "forecast": forecast_block,
            "env": env_block,
        })

    with (out / "beaches.json").open("w") as f:
        json.dump(beach_rows, f, separators=(",", ":"), default=str)
    print(f"  beaches.json: {len(beach_rows)} stations, "
          f"{sum(1 for r in beach_rows if r['has_active_advisory'])} with active advisory",
          file=sys.stderr)

    # parent_beaches.json — group stations by leading beach_id segment (12 hex chars)
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

        # Worst-band aggregation; Advisory outranks every model band
        order = {"Low": 1, "Moderate": 2, "High": 3, "Very High": 4, "Advisory": 5}
        fc = r["forecast"] or {}
        band = fc.get("risk_band")
        pri = order.get(band, 0)
        if pri > p["_band_priority"]:
            p["_band_priority"] = pri
            p["risk_band"] = band
            p["p_exceed"] = fc.get("p_exceed")

    parent_rows = []
    for p in parents.values():
        p.pop("_band_priority", None)
        parent_rows.append(p)

    with (out / "parent_beaches.json").open("w") as f:
        json.dump(parent_rows, f, separators=(",", ":"), default=str)
    print(f"  parent_beaches.json: {len(parent_rows)} parents", file=sys.stderr)

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--curated", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    bake(args.curated, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
