from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from app.schemas.domain import (
    BeachSummary,
    ForecastRecord,
    ObservationResponse,
    SystemHealthResponse,
)


class BeachRepository(ABC):
    @abstractmethod
    def list_beaches(self) -> list[BeachSummary]:
        raise NotImplementedError

    @abstractmethod
    def get_beach(self, beach_id: str) -> BeachSummary:
        raise NotImplementedError

    @abstractmethod
    def get_forecast(self, beach_id: str, forecast_date: date) -> ForecastRecord:
        raise NotImplementedError

    @abstractmethod
    def get_observations(self, beach_id: str) -> ObservationResponse:
        raise NotImplementedError

    @abstractmethod
    def get_system_health(self) -> SystemHealthResponse:
        raise NotImplementedError

