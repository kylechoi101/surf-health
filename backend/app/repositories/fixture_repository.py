from __future__ import annotations

import json
from datetime import date
from functools import cached_property
from pathlib import Path

from fastapi import HTTPException

from app.repositories.base import BeachRepository
from app.schemas.domain import (
    BeachSummary,
    ForecastRecord,
    ObservationResponse,
    SystemHealthResponse,
)


class FixtureBeachRepository(BeachRepository):
    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path

    @cached_property
    def payload(self) -> dict:
        return json.loads(self.fixture_path.read_text())

    def list_beaches(self) -> list[BeachSummary]:
        return [BeachSummary.model_validate(item) for item in self.payload["beaches"]]

    def get_beach(self, beach_id: str) -> BeachSummary:
        for beach in self.payload["beaches"]:
            if beach["id"] == beach_id:
                return BeachSummary.model_validate(beach)
        raise HTTPException(status_code=404, detail=f"Unknown beach '{beach_id}'")

    def get_forecast(self, beach_id: str, forecast_date: date) -> ForecastRecord:
        beach_forecasts = self.payload["forecasts"].get(beach_id, {})
        entry = beach_forecasts.get(forecast_date.isoformat())
        if not entry:
            raise HTTPException(status_code=404, detail="Forecast not available for requested date")
        return ForecastRecord.model_validate(
            {"beach_id": beach_id, "forecast_date": forecast_date.isoformat(), **entry}
        )

    def get_observations(self, beach_id: str) -> ObservationResponse:
        payload = self.payload["observations"].get(beach_id)
        if not payload:
            raise HTTPException(status_code=404, detail="Observation history not available")
        return ObservationResponse.model_validate({"beach_id": beach_id, **payload})

    def get_system_health(self) -> SystemHealthResponse:
        payload = self.payload["system_health"]
        return SystemHealthResponse.model_validate({
            "app_env": "development",
            "active_advisories_count": 5,
            **payload
        })

