import os
from datetime import date

os.environ["PREFERRED_REPOSITORY"] = "fixture"

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_list_beaches_returns_fixture_payload():
    response = client.get("/beaches")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) >= 3
    assert payload[0]["county"] <= payload[-1]["county"]


def test_forecast_endpoint_returns_expected_contract():
    response = client.get("/beaches/scripps-pier/forecast", params={"date": date(2026, 4, 20)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["risk_band"] == "Moderate"
    assert "top_drivers" in payload


def test_system_health_endpoint():
    response = client.get("/system/health")
    assert response.status_code == 200
    payload = response.json()
    assert "model_registry" in payload
