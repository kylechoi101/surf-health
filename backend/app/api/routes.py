from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.repositories.base import BeachRepository
from app.repositories.factory import build_repository
from app.services.beach_service import BeachService


def get_repository(settings: Settings = Depends(get_settings)) -> BeachRepository:
    return build_repository(settings)


def get_service(
    repository: BeachRepository = Depends(get_repository),
) -> BeachService:
    return BeachService(repository)


router = APIRouter()


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
    return service.get_system_health()
