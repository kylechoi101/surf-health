from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Response

from app.core.config import get_settings
from app.repositories.base import BeachRepository
from app.repositories.factory import build_repository
from app.services.beach_service import BeachService


@lru_cache(maxsize=1)
def get_repository() -> BeachRepository:
    return build_repository(get_settings())


def get_service(
    repository: BeachRepository = Depends(get_repository),
) -> BeachService:
    return BeachService(repository)


router = APIRouter()

# Forecast/advisory/beach payloads come from the baked snapshot, but a 24h
# edge TTL kept serving pre-recovery data for a full day after a stale
# snapshot was fixed. One hour caps that exposure; stale-while-revalidate
# keeps the edge fast while it refetches in the background.
SNAPSHOT_CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=600"


@router.get("/parent-beaches")
def list_parent_beaches(response: Response, service: BeachService = Depends(get_service)):
    response.headers["Cache-Control"] = SNAPSHOT_CACHE_CONTROL
    return service.list_parent_beaches()


@router.get("/beaches")
def list_beaches(response: Response, service: BeachService = Depends(get_service)):
    response.headers["Cache-Control"] = SNAPSHOT_CACHE_CONTROL
    return service.list_beaches()


@router.get("/beaches/{beach_id}/forecast")
def get_forecast(
    beach_id: str,
    date: date,
    response: Response,
    service: BeachService = Depends(get_service),
):
    payload = service.get_forecast(beach_id, date)
    response.headers["Cache-Control"] = SNAPSHOT_CACHE_CONTROL
    return payload


@router.get("/beaches/{beach_id}/observations")
def get_observations(
    beach_id: str,
    response: Response,
    service: BeachService = Depends(get_service),
):
    response.headers["Cache-Control"] = SNAPSHOT_CACHE_CONTROL
    return service.get_observations(beach_id)


@router.get("/beaches/{beach_id}/forecast/explain")
def explain_forecast(
    beach_id: str,
    date: date,
    response: Response,
    service: BeachService = Depends(get_service),
):
    response.headers["Cache-Control"] = SNAPSHOT_CACHE_CONTROL
    return service.explain_forecast(beach_id, date)


@router.get("/beaches/{beach_id}/hourly")
async def get_hourly(
    beach_id: str,
    response: Response,
    service: BeachService = Depends(get_service),
):
    """Hourly intra-day series for Surfline-style charts on the client.
    Returns wind, UV, temperature, wave height/period/direction at hourly
    resolution from yesterday-noon through ~48h ahead. Cached server-side
    for 3 hours per 0.1° lat/lon grid cell."""
    from app.services.hourly_store import get_precomputed_hourly
    from app.services.hourly_weather import fetch_hourly

    # Look up the beach to get coordinates. get_beach raises 404 if unknown.
    beach = service.repository.get_beach(beach_id)
    lat, lon = beach.geometry.latitude, beach.geometry.longitude

    # Serve the precomputed snapshot first (built by the daily pipeline from a
    # non-throttled IP). The live per-request Open-Meteo path gets rate-limited
    # from the production server, so it is now only a fallback for cells the
    # snapshot doesn't cover.
    payload = get_precomputed_hourly(get_settings().curated_dir, lat, lon)
    if payload is None:
        payload = await fetch_hourly(lat, lon)
    if payload is None:
        raise HTTPException(status_code=502, detail="upstream weather service unavailable")
    response.headers["Cache-Control"] = "public, max-age=10800, stale-while-revalidate=3600"
    return {"beach_id": beach_id, **payload}


@router.get("/beaches/{beach_id}/tides")
def get_tides(
    beach_id: str,
    response: Response,
    service: BeachService = Depends(get_service),
):
    """48 h of hourly tide predictions for the nearest NOAA CO-OPS station.
    Returns predictions, derived high/low extrema, and the nearest-station
    metadata. Cached server-side for 24 h per station (predictions are
    deterministic harmonic outputs)."""
    from app.services.tides import fetch_tides

    beach = service.repository.get_beach(beach_id)
    payload = fetch_tides(beach.geometry.latitude, beach.geometry.longitude)
    if payload is None:
        raise HTTPException(status_code=502, detail="upstream tide service unavailable")
    response.headers["Cache-Control"] = "public, max-age=21600, stale-while-revalidate=3600"
    return {"beach_id": beach_id, **payload}


@router.get("/system/health")
def system_health(service: BeachService = Depends(get_service)):
    health = service.get_system_health()

    reasons: list[str] = []

    # -- Pipeline freshness check (skip sentinel values used in fixtures/dev) --
    freshness_raw = health.pipeline_freshness
    _SENTINEL = {"fixtures-current", "development", "unknown"}
    if freshness_raw not in _SENTINEL:
        try:
            # Accept ISO-8601 with or without timezone offset
            freshness_dt = datetime.fromisoformat(freshness_raw)
            if freshness_dt.tzinfo is None:
                freshness_dt = freshness_dt.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - freshness_dt
            if age > timedelta(hours=36):
                reasons.append(
                    f"pipeline_freshness is {int(age.total_seconds() // 3600)} h old (limit 36 h)"
                )
        except ValueError:
            reasons.append(f"pipeline_freshness is not a parseable timestamp: {freshness_raw!r}")

    # -- Model registry checks --
    registry = health.model_registry or {}

    if not registry.get("public_release_eligible", False):
        reasons.append("model_registry.public_release_eligible is not true")

    prod_metrics = registry.get("production_metrics") or {}
    if not prod_metrics or "aucpr" not in prod_metrics:
        reasons.append("model_registry.production_metrics is missing or has no aucpr")

    if reasons:
        raise HTTPException(
            status_code=503,
            detail={"status": "unhealthy", "reasons": reasons},
        )

    return health
