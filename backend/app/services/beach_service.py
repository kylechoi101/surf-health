from __future__ import annotations

from datetime import date

from app.repositories.base import BeachRepository
from app.schemas.domain import (
    BeachSummary,
    ForecastExplanationResponse,
    ForecastRecord,
    ObservationResponse,
    SystemHealthResponse,
)


class BeachService:
    def __init__(self, repository: BeachRepository) -> None:
        self.repository = repository

    def list_beaches(self) -> list[BeachSummary]:
        return sorted(self.repository.list_beaches(), key=lambda item: (item.county, item.name))

    def get_forecast(self, beach_id: str, forecast_date: date) -> ForecastRecord:
        return self.repository.get_forecast(beach_id, forecast_date)

    def get_observations(self, beach_id: str) -> ObservationResponse:
        return self.repository.get_observations(beach_id)

    def get_system_health(self) -> SystemHealthResponse:
        return self.repository.get_system_health()

    def explain_forecast(self, beach_id: str, forecast_date: date) -> ForecastExplanationResponse:
        beach = self.repository.get_beach(beach_id)
        forecast = self.repository.get_forecast(beach_id, forecast_date)
        drivers = forecast.top_drivers[:2]
        driver_line = (
            "Key factors: " + "; ".join(drivers) + "."
            if drivers
            else "No strong environmental signal detected."
        )
        summary = (
            f"{beach.name} is forecast at {forecast.risk_band.lower()} risk today. "
            f"The model estimates a {forecast.p_exceed:.0%} chance of exceeding the marine "
            f"enterococcus threshold. {driver_line} "
            "This is a forecast, not a direct lab result — treat uncertainty seriously "
            "if you have a cut or a weaker immune system."
        )
        return ForecastExplanationResponse(
            beach_id=forecast.beach_id,
            summary=summary,
            used_model="template-v1",
        )

