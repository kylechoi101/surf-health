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
    # The fixture payload has public_release_eligible=false, so the guard returns 503.
    # A 503 is still a valid structured response — verify the body shape.
    response = client.get("/system/health")
    assert response.status_code in (200, 503)
    payload = response.json()
    # 200 path: full health document; 503 path: {"detail": {"status": "unhealthy", ...}}
    if response.status_code == 200:
        assert "model_registry" in payload
    else:
        assert payload["detail"]["status"] == "unhealthy"
        assert "reasons" in payload["detail"]


def test_system_health_returns_503_when_pipeline_stale(monkeypatch):
    """Guard returns 503 when pipeline_freshness is older than 36 hours."""
    import app.api.routes as r
    from app.schemas.domain import SystemHealthResponse
    from datetime import datetime, timezone, timedelta

    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=40)).isoformat()

    stale_health = SystemHealthResponse(
        app_env="test",
        pipeline_freshness=stale_ts,
        source_freshness={},
        model_registry={
            "public_release_eligible": True,
            "production_metrics": {"aucpr": 0.72},
        },
    )

    def fake_get_system_health():
        return stale_health

    original_build = r.build_repository

    class FakeService:
        def get_system_health(self):
            return stale_health

    class FakeRepo:
        pass

    r.get_repository.cache_clear()
    monkeypatch.setattr(r, "build_repository", lambda s: FakeRepo())
    monkeypatch.setattr(
        "app.services.beach_service.BeachService.get_system_health",
        lambda self: stale_health,
    )

    response = client.get("/system/health")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["status"] == "unhealthy"
    assert any("pipeline_freshness" in reason for reason in detail["reasons"])

    r.get_repository.cache_clear()
    monkeypatch.setattr(r, "build_repository", original_build)


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
