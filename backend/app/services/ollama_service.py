from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.schemas.domain import ForecastExplanationResponse, ForecastRecord


@dataclass
class OllamaNarrator:
    base_url: str
    model_name: str

    async def describe(self, beach_name: str, forecast: ForecastRecord) -> ForecastExplanationResponse:
        fallback = self._fallback_summary(beach_name, forecast)
        prompt = (
            "You explain recreational water-health forecasts to surfers in plain language. "
            "Be concise, calm, and specific. Mention uncertainty once. "
            f"Beach: {beach_name}. Risk band: {forecast.risk_band}. "
            f"Probability of exceedance: {forecast.p_exceed:.2f}. "
            f"Predicted log10 enterococcus: {forecast.predicted_log_enterococcus}. "
            f"Top drivers: {', '.join(forecast.top_drivers)}."
        )
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": self.model_name, "prompt": prompt, "stream": False},
                )
                response.raise_for_status()
                summary = response.json().get("response", "").strip() or fallback
        except Exception:
            summary = fallback

        return ForecastExplanationResponse(
            beach_id=forecast.beach_id,
            summary=summary,
            used_model=self.model_name,
        )

    @staticmethod
    def _fallback_summary(beach_name: str, forecast: ForecastRecord) -> str:
        drivers = forecast.top_drivers[:2]
        driver_line = (
            "Key factors: " + "; ".join(drivers) + "."
            if drivers
            else "No strong environmental signal detected."
        )
        return (
            f"{beach_name} is forecast at {forecast.risk_band.lower()} risk today. "
            f"The model estimates a {forecast.p_exceed:.0%} chance of exceeding the marine "
            f"enterococcus threshold. {driver_line} "
            "This is a forecast, not a direct lab result — treat uncertainty seriously "
            "if you have a cut or a weaker immune system."
        )

