import os
from datetime import date

os.environ["PREFERRED_REPOSITORY"] = "fixture"

from fastapi.testclient import TestClient

from app.api import routes
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


def test_cors_allows_public_web_origin_without_wildcard():
    origin = "https://kylechoi101.github.io"

    response = client.get("/system/health", headers={"Origin": origin})

    assert response.headers["access-control-allow-origin"] == origin


def test_cors_rejects_unknown_origin():
    response = client.get("/system/health", headers={"Origin": "https://example.invalid"})

    assert "access-control-allow-origin" not in response.headers


def test_repository_dependency_is_cached(monkeypatch):
    routes.get_repository.cache_clear()
    calls = []

    def fake_build_repository(settings):
        calls.append(settings)
        return object()

    monkeypatch.setattr(routes, "build_repository", fake_build_repository)

    first = routes.get_repository()
    second = routes.get_repository()

    assert first is second
    assert len(calls) == 1

    routes.get_repository.cache_clear()
