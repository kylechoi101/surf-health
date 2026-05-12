from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException

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


@router.get("/parent-beaches")
def list_parent_beaches(service: BeachService = Depends(get_service)):
    return service.list_parent_beaches()


@router.get("/beaches")
def list_beaches(service: BeachService = Depends(get_service)):
    return service.list_beaches()


@router.get("/beaches/{beach_id}/forecast")
def get_forecast(beach_id: str, date: date, service: BeachService = Depends(get_service)):
    return service.get_forecast(beach_id, date)


@router.get("/beaches/{beach_id}/observations")
def get_observations(beach_id: str, service: BeachService = Depends(get_service)):
    return service.get_observations(beach_id)


@router.get("/beaches/{beach_id}/forecast/explain")
def explain_forecast(beach_id: str, date: date, service: BeachService = Depends(get_service)):
    return service.explain_forecast(beach_id, date)


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
