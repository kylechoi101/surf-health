"""Public, privacy-preserving closure feed for nearby-closure notifications.

The server pools currently-active beach closures/advisories (with lat/lon) into
a small public feed. The mobile app fetches it on a background schedule and
decides ON-DEVICE whether any closure is within the user's radius — the user's
location never leaves the phone and the server stores no user data. Each entry
carries a stable ``closure_id`` so the device can avoid notifying twice.
"""

from __future__ import annotations

import hashlib

import pandas as pd

from app.repositories.curated_repository import filter_currently_active


def closure_id(beach_id: str, started_at) -> str:
    """Deterministic id for a closure, stable across hourly refreshes so the
    device can dedup. Keyed on (beach_id, started_at) — a re-posting gets a new
    started_at and therefore a new id (correctly re-notifies)."""
    key = f"{beach_id}|{started_at}".encode()
    return hashlib.sha1(key).hexdigest()[:12]


def build_closures_feed(advisories: pd.DataFrame, beaches: pd.DataFrame) -> list[dict]:
    """Return the list of currently-active closures joined to beach coordinates.

    Entries without coordinates are dropped (proximity needs lat/lon). Output is
    JSON-ready dicts with a stable ``closure_id``.
    """
    active = filter_currently_active(advisories)
    if active.empty or beaches.empty:
        return []

    coords = beaches[["beach_id", "name", "county", "latitude", "longitude"]].drop_duplicates("beach_id")
    merged = active.merge(coords, on="beach_id", how="left", suffixes=("", "_beach"))
    merged = merged.loc[merged["latitude"].notna() & merged["longitude"].notna()]
    if merged.empty:
        return []

    feed: list[dict] = []
    for _, r in merged.iterrows():
        started = r.get("started_at")
        feed.append(
            {
                "closure_id": closure_id(str(r["beach_id"]), started),
                "beach_id": str(r["beach_id"]),
                "name": (r.get("name") if pd.notna(r.get("name")) else None),
                "county": (r.get("county") if pd.notna(r.get("county")) else None),
                "latitude": float(r["latitude"]),
                "longitude": float(r["longitude"]),
                "advisory_type": (r.get("advisory_type") if pd.notna(r.get("advisory_type")) else None),
                "cause": (r.get("cause") if pd.notna(r.get("cause")) else None),
                "started_at": (str(started) if pd.notna(started) else None),
                "advisory_website": (
                    r.get("advisory_website") if pd.notna(r.get("advisory_website")) else None
                ),
            }
        )
    return feed
