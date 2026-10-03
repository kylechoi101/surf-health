"""Parity: `bake_web_static.py --with-details` vs the API's own code.

The baker is curl'd standalone by shorelife-web's deploy and cannot import `app`,
so it carries ports of `ServingSnapshotRepository` / `BeachService`. This bakes a
small fixture, builds `serving.sqlite` from the SAME curated dir, runs the real
`BeachService` over it (the production path: `factory.build_repository`), and
requires every `api/*` payload to equal what the routes would return. It also
pins each vendored twin against its `app` original.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pandas as pd
import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.data.pipeline import cli
from app.data.pipeline import serving_snapshot as snapshot
from app.data.pipeline.serving_snapshot import build_serving_snapshot
from app.repositories import serving_repository as serving
from app.repositories._coerce import derive_friendly_name
from app.repositories.factory import build_repository
from app.schemas.domain import (
    BeachSummary,
    ForecastExplanationResponse,
    ForecastRecord,
    ObservationResponse,
    ParentBeachSummary,
    SystemHealthResponse,
    sample_recency_band,
)
from app.services import shore_normal, tides as tides_service
from app.services.beach_service import BeachService
from app.services.hourly_store import get_precomputed_hourly
from scripts import bake_web_static as bake

FORECAST_DATE = "2026-04-20"
NOW = datetime.now(timezone.utc)

A = "ca123-orange-main-beach-main-beach-pier"  # posted, parent P1
B = "ca123-orange-main-beach-main-beach-north"  # sibling of A, lifted posting, very stale sample
C = "ca555-orange-cove-cove-center"  # only an OLD forecast row -> fallback row
D = "ca777-los-angeles-bay-bay-dock"  # no forecast, no observations, no parent
E = "ca888-san-diego-point-point-south"  # fresh forecast, no advisory


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=None).isoformat(timespec="seconds")


def _write_curated(curated: Path) -> None:
    curated.mkdir()
    pd.DataFrame(
        [
            {"beach_id": A, "name": "Main Beach Pier", "beach_name": "Main Beach", "station_code": "MB-1",
             "county": "Orange", "region": "Santa Ana", "support_status": "production",
             "latest_official_sample_at": "2026-04-18T08:00:00", "latitude": 33.60, "longitude": -117.90},
            {"beach_id": B, "name": "North \\'Stairs", "beach_name": "", "station_code": "MB-2",
             "county": "Orange", "region": "Santa Ana", "support_status": "production",
             "latest_official_sample_at": "2026-01-01T08:00:00", "latitude": 33.61, "longitude": -117.91},
            {"beach_id": C, "name": "Cove Center", "beach_name": "Cove", "station_code": "CV-1",
             "county": "Orange", "region": "Santa Ana", "support_status": "beta",
             "latest_official_sample_at": "2026-04-19T08:00:00", "latitude": 33.55, "longitude": -117.85},
            {"beach_id": D, "name": "Bay Dock", "beach_name": None, "station_code": None,
             "county": "Los Angeles", "region": "Los Angeles", "support_status": "unsupported",
             "latest_official_sample_at": None, "latitude": 33.75, "longitude": -118.20},
            {"beach_id": E, "name": "Point South", "beach_name": "Point", "station_code": "PT-1",
             "county": "San Diego", "region": "San Diego", "support_status": "production",
             "latest_official_sample_at": "2026-04-19T08:00:00", "latitude": 32.80, "longitude": -117.25},
        ]
    ).to_parquet(curated / "beaches.parquet", index=False)

    pd.DataFrame(
        [
            {"parent_beach_id": "parent-ca123", "name": "Main Beach", "county": "Orange", "region": "Santa Ana",
             "support_status": "production", "latitude": 33.605, "longitude": -117.905, "station_count": 2,
             "member_beach_ids": [A, B], "latest_official_sample_at": "2026-04-18T08:00:00"},
            {"parent_beach_id": "parent-ca555", "name": "Cove", "county": "Orange", "region": "Santa Ana",
             "support_status": "beta", "latitude": 33.55, "longitude": -117.85, "station_count": 1,
             "member_beach_ids": [C], "latest_official_sample_at": "2026-04-19T08:00:00"},
        ]
    ).to_parquet(curated / "parent_beaches.parquet", index=False)

    fresh = _iso(NOW - timedelta(hours=1, minutes=30))
    old = _iso(NOW - timedelta(hours=100, minutes=30))
    pd.DataFrame(
        [
            {"beach_id": A, "forecast_date": FORECAST_DATE, "risk_band": "High", "p_exceed": 0.72,
             "p_exceed_raw": 0.18, "p_exceed_lower": 0.6, "p_exceed_upper": 0.8, "advisory_floor_applied": True,
             "predicted_log_enterococcus": 2.1, "prediction_interval_level": 0.9,
             "top_drivers": ["recent high sample", "waves elevated", "rain"], "model_version": "m-1",
             "forecast_generated_at": old, "sample_age_days": 2, "wave_height_m": 1.2, "uv_index": 6.0},
            {"beach_id": B, "forecast_date": FORECAST_DATE, "risk_band": "High", "p_exceed": 0.8,
             "p_exceed_raw": 0.8, "top_drivers": ["x"], "model_version": "m-1", "forecast_generated_at": fresh,
             "forecast_label_mode": "model"},
            {"beach_id": C, "forecast_date": "2026-04-18", "risk_band": "Low", "p_exceed": 0.05,
             "p_exceed_raw": float("nan"), "top_drivers": [], "model_version": "m-0",
             "forecast_generated_at": None},
            {"beach_id": E, "forecast_date": FORECAST_DATE, "risk_band": "Moderate", "p_exceed": 0.25,
             "p_exceed_raw": 0.25, "p_exceed_lower": 0.0, "top_drivers": [], "model_version": "m-1",
             "forecast_generated_at": fresh, "is_beta_forecast": False},
        ]
    ).to_parquet(curated / "forecasts.parquet", index=False)

    pd.DataFrame(
        [{"beach_id": A, "wave_height_m": 1.1, "dominant_period_s": 8.0, "water_temperature_c": 16.2,
          "salinity_psu": 33.0, "uv_index": 5.0, "wind_speed_mps": 3.0, "wind_direction_deg": 220.0},
         {"beach_id": E, "wave_height_m": 0.7, "dominant_period_s": 11.0, "water_temperature_c": 17.0,
          "salinity_psu": 33.5, "uv_index": 4.0, "wind_speed_mps": 2.0, "wind_direction_deg": 200.0}]
    ).to_parquet(curated / "latest_env.parquet", index=False)

    observations, beach_day = [], []
    for bid, count in ((A, 60), (B, 3), (C, 5), (E, 2)):
        for idx in range(count):
            day = pd.Timestamp("2026-02-01") + pd.Timedelta(days=idx)
            observations.append({
                "beach_id": bid, "sample_time": day.isoformat(), "sample_date": day.date().isoformat(),
                "analyte": "enterococcus", "method": "Culture", "units": "CFU/100ml",
                "value": 10.0 + idx, "exceeds_stv": idx % 7 == 0, "weather": "clear", "storm_drain_flow": "none",
            })
            beach_day.append({
                "beach_id": bid, "sample_date": day.date().isoformat(), "wave_height_m": 1.0 + idx / 100,
                "dominant_period_s": 9.0, "water_temperature_c": 15.0, "salinity_psu": 33.0,
                "weather": "clear", "storm_drain_flow": "none", "tidal_height": 0.5,
                "surf_height_observed": 2.0, "turbidity_observed": None,
                "wind_speed_24h_max": 4.0, "wind_direction_24h_mean": 250.0, "uv_index_24h_max": 7.0,
            })
    # Equal-timestamp samples: the API's index scan returns them in reverse table order.
    for value in (30.0, 20.0, 25.0):
        observations.append({
            "beach_id": E, "sample_time": "2026-03-01T09:05:00", "sample_date": "2026-03-01",
            "analyte": "enterococcus", "method": "Enterolert", "units": "MPN/100ml",
            "value": value, "exceeds_stv": False, "weather": None, "storm_drain_flow": None,
        })
    pd.DataFrame(observations).to_parquet(curated / "observations.parquet", index=False)
    pd.DataFrame(beach_day).to_parquet(curated / "beach_day.parquet", index=False)

    pd.DataFrame(
        [
            {"beach_id": A, "advisory_type": "Posting", "started_at": _iso(NOW - timedelta(days=2)),
             "ended_at": None, "status": "active", "advisory_website": "https://county.example/a"},
            {"beach_id": A, "advisory_type": "Posting", "started_at": "2025-12-01T00:00:00",
             "ended_at": "2025-12-05T00:00:00", "status": "historical", "advisory_website": "unknown"},
            {"beach_id": B, "advisory_type": "Posting", "started_at": _iso(NOW - timedelta(days=3)),
             "ended_at": _iso(NOW - timedelta(days=1)), "status": "active", "advisory_website": None},
            # two live postings with the same start: the first row's URL is the one served
            {"beach_id": E, "advisory_type": "Posting", "started_at": _iso(NOW - timedelta(days=1)),
             "ended_at": None, "status": "active", "advisory_website": "https://county.example/e1"},
            {"beach_id": E, "advisory_type": "Advisory", "started_at": _iso(NOW - timedelta(days=1)),
             "ended_at": None, "status": "active", "advisory_website": "https://county.example/e2"},
            {"beach_id": C, "advisory_type": "Closure", "started_at": "2025-10-13T00:00:00",
             "ended_at": None, "status": "active", "advisory_website": "https://county.example/c"},
        ]
    ).to_parquet(curated / "advisories.parquet", index=False)

    payload = {"lat_r": 33.6, "lon_r": -117.9}
    pd.DataFrame(
        [{"lat_r": 33.6, "lon_r": -117.9, "payload_json": json.dumps({"hours": [1, 2, 3], **payload})}]
    ).to_parquet(curated / "hourly_forecast.parquet", index=False)

    (curated / "system_health.json").write_text(json.dumps({
        "pipeline_freshness": "2026-04-20T13:00:00+00:00",
        "source_freshness": {"beachwatch": "2026-04-19"},
        "model_registry": {"production_model": "m-1"},
        "served_metrics": {"extra": "research section"},
    }))
    (curated / "advisory_audit.json").write_text(json.dumps({
        "generated_at": "2026-04-20", "agreement_rate": 0.9,
        "false_negatives": {"count": 1}, "false_positives": {"count": 2}, "active_advisories": 2,
    }))


def _tides_frame() -> tuple[pd.DataFrame, MagicMock]:
    """Built by the real pipeline step from a fake NOAA response, for the station near A."""
    start = NOW.replace(minute=0, second=0, microsecond=0, tzinfo=None) - timedelta(hours=10)
    preds = [{"t": (start + timedelta(hours=h)).strftime("%Y-%m-%d %H:%M"), "v": f"{2.5 * math.sin(h / 1.98):.3f}"}
             for h in range(10 + 96 + 1)]
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"predictions": preds}
    client = MagicMock(spec=httpx.Client)
    client.get.return_value = resp
    beaches = pd.DataFrame({"beach_id": [A], "latitude": [33.60], "longitude": [-117.90]})
    tides_service._CACHE.clear()
    frame = cli.build_tides_frame(beaches, client=client)
    tides_service._CACHE.clear()
    return frame, client


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("parity")
    curated = root / "curated"
    _write_curated(curated)
    tides, client = _tides_frame()
    tides.to_parquet(curated / "tides.parquet", index=False)
    build_serving_snapshot(curated)
    out = root / "bake"
    bake.bake(curated, out, with_details=True)
    service = BeachService(build_repository(Settings(curated_dir=curated, preferred_repository="serving")))
    return {"curated": curated, "out": out, "service": service, "client": client}


def _load(env, name):
    return json.loads((env["out"] / "api" / name).read_text())


def test_bake_without_flag_writes_no_api_dir(tmp_path):
    curated = tmp_path / "curated"
    _write_curated(curated)
    bake.bake(curated, tmp_path / "out")
    assert not (tmp_path / "out" / "api").exists()
    assert {p.name for p in (tmp_path / "out").iterdir()} == {
        "beaches.json", "parent_beaches.json", "regional_summary.json"}


def test_beaches_match_list_beaches(env):
    rows = _load(env, "beaches.json")
    expected = env["service"].list_beaches()
    assert [r["id"] for r in rows] == [b.id for b in expected]
    assert [BeachSummary.model_validate(r) for r in rows] == expected
    # shore normal is actually populated, so the SVD twin is exercised
    assert any(b.shore_normal_deg is not None for b in expected)


def test_beach_forecasts_match_get_forecast(env):
    rows = {r["id"]: r for r in _load(env, "beaches.json")}
    service = env["service"]
    d = date.fromisoformat(FORECAST_DATE)
    seen = set()
    for bid, row in rows.items():
        try:
            api = service.get_forecast(bid, d)
        except HTTPException:
            api = None
        forecast = row["forecast"]
        if bid == D:
            # no forecasts row: the API derives/404s; the bake says null (client falls back)
            assert forecast is None
            continue
        assert forecast is not None, bid
        baked = ForecastRecord.model_validate(forecast)
        assert baked == api, bid
        seen.add(bid)
    assert seen == {A, B, C, E}
    # the interesting branches are really covered
    assert rows[A]["forecast"]["official_advisory_active"] and rows[A]["forecast"]["advisory_floor_applied"]
    assert rows[B]["forecast"]["parent_has_active_advisory"]
    assert rows[B]["forecast"]["risk_band"] == "Moderate"  # confidence cap (very stale sample)
    assert rows[C]["forecast"]["is_stale"] and rows[C]["forecast"]["forecast_date"] == "2026-04-18"
    assert rows[E]["forecast"]["is_stale"] is False
    assert rows[E]["forecast"]["advisory_website"] == "https://county.example/e1"  # tie -> table order


def test_parent_beaches_match_list_parent_beaches(env):
    rows = _load(env, "parent_beaches.json")
    expected = env["service"].list_parent_beaches()
    assert [ParentBeachSummary.model_validate(r) for r in rows] == expected
    main = next(p for p in expected if p.id == "parent-ca123")
    assert main.has_active_advisory and main.flagged_station_count == 1


def test_health_validates_and_matches_the_api(env):
    health = _load(env, "health.json")
    baked = SystemHealthResponse.model_validate(health)
    api = env["service"].get_system_health()
    for field in ("pipeline_freshness", "source_freshness", "model_registry",
                  "active_advisories_count", "forecast_audit"):
        assert getattr(baked, field) == getattr(api, field), field
    assert baked.repository_mode == "static"
    assert health["served_metrics"] == {"extra": "research section"}


def test_every_beach_has_a_file_with_sections_matching_the_api(env):
    rows = _load(env, "beaches.json")
    files = sorted(p.stem for p in (env["out"] / "api" / "beach").glob("*.json"))
    assert files == sorted(r["id"] for r in rows)
    service = env["service"]
    d = date.fromisoformat(FORECAST_DATE)
    for row in rows:
        bid = row["id"]
        doc = json.loads((env["out"] / "api" / "beach" / f"{bid}.json").read_text())
        assert doc["beach_id"] == bid and doc["forecast_date"] == FORECAST_DATE
        assert set(doc) == {"beach_id", "forecast_date", "generated_at", "observations", "explain", "hourly", "tides"}

        try:
            api_obs = service.get_observations(bid)
        except HTTPException:
            assert doc["observations"] is None
        else:
            baked = ObservationResponse.model_validate(doc["observations"])
            # The contract ships the newest 52 samples; serving.sqlite keeps 25.
            assert len(baked.observations) == min(52, 60 if bid == A else len(api_obs.observations))
            assert baked.observations[: len(api_obs.observations)] == api_obs.observations
            assert baked.advisories == api_obs.advisories
            assert baked.recent_environment == api_obs.recent_environment
            assert all(
                a.sample_time >= b.sample_time for a, b in zip(baked.observations, baked.observations[1:])
            )

        if row["forecast"] is None:
            assert doc["explain"] is None
        else:
            api_explain = service.explain_forecast(bid, d)
            assert ForecastExplanationResponse.model_validate(doc["explain"]) == api_explain

        beach = service.repository.get_beach(bid)
        cell = get_precomputed_hourly(env["curated"], beach.geometry.latitude, beach.geometry.longitude)
        assert doc["hourly"] == (None if cell is None else {"beach_id": bid, **cell})


def test_observations_cap_is_52_not_the_api_25(env):
    doc = json.loads((env["out"] / "api" / "beach" / f"{A}.json").read_text())
    assert len(doc["observations"]["observations"]) == 52
    assert len(env["service"].get_observations(A).observations) == 25


def test_tides_section_equals_the_routes_payload_window(env):
    doc = json.loads((env["out"] / "api" / "beach" / f"{A}.json").read_text())
    beach = env["service"].repository.get_beach(A)
    sid, sname, dist = tides_service.nearest_station(beach.geometry.latitude, beach.geometry.longitude)
    route = tides_service.fetch_station_tides(sid, sname, dist, hours_ahead=96, use_cache=False,
                                              _client=env["client"])
    tides = doc["tides"]
    assert {k: tides[k] for k in ("beach_id", "station_id", "station_name", "station_distance_km")} == {
        "beach_id": A, "station_id": route["station_id"], "station_name": route["station_name"],
        "station_distance_km": route["station_distance_km"]}
    assert set(tides) == {"beach_id", "station_id", "station_name", "station_distance_km", "predictions", "extrema"}
    first = tides["predictions"][0]["t"]
    assert tides["predictions"] == [p for p in route["predictions"] if p["t"] >= first]
    assert tides["extrema"] == [e for e in route["extrema"] if e["t"] >= first]
    # beaches that map to a station with no rows get null, not an error
    other = json.loads((env["out"] / "api" / "beach" / f"{E}.json").read_text())
    assert other["tides"] is None


# --------------------------- vendored twins vs `app` ---------------------------- #

def test_station_list_equals_the_apps():
    assert bake._CA_TIDE_STATIONS == tides_service.CA_TIDE_STATIONS


def test_nearest_station_matches_the_apps():
    for lat, lon in ((33.6, -117.9), (37.76, -122.51), (41.0, -124.0), (32.5, -117.1), (35.0, -120.6)):
        sid, name, dist = bake._nearest_tide_station(lat, lon)
        assert (sid, name) == tides_service.nearest_station(lat, lon)[:2]
        assert dist == pytest.approx(tides_service.nearest_station(lat, lon)[2])


def test_advisory_auto_expire_days_matches_the_snapshot_builder():
    assert bake.ADVISORY_AUTO_EXPIRE_DAYS == snapshot.ADVISORY_AUTO_EXPIRE_DAYS
    assert bake.ACTIVE_WINDOW_DAYS == serving.ServingSnapshotRepository._ACTIVE_ADVISORY_WINDOW_DAYS
    assert bake.ENVIRONMENT_LIMIT == snapshot.ENVIRONMENT_LIMIT


_NAME_CASES = [
    ("ca123-orange-main-beach-main-beach-pier", "Orange", "Main Beach Pier", ""),
    ("ca123-orange-main-beach-main-beach-pier", "Orange", "Main Beach Pier", "Main Beach"),
    ("ca9-long-beach-city-long-beach-b-10", "Los Angeles", "Long Beach B 10", ""),
    ("ca1-san-diego-point-south", "San Diego", "Something Else", ""),
    ("plain", "", "", ""),
    ("ca1-x", "X", "", "  "),
]


@pytest.mark.parametrize("args", _NAME_CASES)
def test_friendly_name_twin(args):
    assert bake._derive_friendly_name(*args) == derive_friendly_name(*args)


@pytest.mark.parametrize("drivers", [[], ["a"], ["a", "b", "c"]])
@pytest.mark.parametrize("p", [0.0, 0.049, 0.5, 1.0])
def test_explain_summary_twin_matches_the_service_template(p, drivers):
    summary = bake.explain_summary("Main Beach", "High", p, drivers)
    assert summary.startswith("Main Beach is forecast at high risk today. ")
    assert f"{p:.0%} chance" in summary
    assert ("Key factors: " + "; ".join(drivers[:2]) + ".") in summary if drivers else (
        "No strong environmental signal detected." in summary)


def test_serve_time_band_twin_matches_the_repository():
    values = [None, 0.0, 0.1, 0.2, 0.29, 0.3, 0.69, 0.7, 0.95]
    bands = [None, "fresh", "recent", "stale", "very_stale", "unknown"]
    for raw in values:
        for stored in values:
            for active in (True, False):
                for band in bands:
                    assert bake._serve_time_band(raw, stored, active_advisory=active, recency_band=band) == \
                        serving.serve_time_band(raw, stored, active_advisory=active, recency_band=band)


def test_sample_recency_band_twin():
    for age in [None, 0, 3, 4, 20, 21, 60, 61, 400]:
        assert bake._sample_recency_band(age) == sample_recency_band(age)


def test_shore_normal_twin_matches_the_apps():
    population = [("a", 33.60, -117.90), ("b", 33.61, -117.91), ("c", 33.55, -117.85),
                  ("d", 33.75, -118.20), ("e", 32.80, -117.25), ("f", 33.0, -117.3), ("g", 34.0, -118.5)]
    shore_normal.clear_cache()
    for bid, _, _ in population:
        assert bake._shore_normal_deg(bid, population) == pytest.approx(
            shore_normal.compute_shore_normal_deg(bid, population))
    assert bake._shore_normal_deg("missing", population) is None


def test_coercion_twins_match_the_apps():
    from app.repositories import _coerce

    def call(fn, *args, **kwargs):
        try:
            return ("ok", repr(fn(*args, **kwargs)))
        except Exception as exc:  # noqa: BLE001 — parity includes failure modes
            return ("raise", type(exc).__name__)

    for value in [None, "", "nan", float("nan"), 0, 1.5, "2", True, "false", "unknown", object()]:
        assert call(bake._sf, value) == call(_coerce.safe_float, value)
        assert call(bake._si, value) == call(_coerce.safe_int, value)
        for default in (True, False):
            assert call(bake._sb, value, default) == call(_coerce.safe_bool, value, default=default)
        assert call(bake._advisory_website, value) == call(_coerce.coerce_advisory_website, value)


def test_json_list_matches_snapshot_roundtrip():
    import numpy as np

    for value in [None, float("nan"), [], ["a", "b"], np.array(["a"]), np.array(["a", "b"]), '["x"]', "bad", "{}"]:
        stored = snapshot._json_dumps(value)
        assert bake._json_list(value) == [str(v) for v in serving._parse_json_list(stored)]


def test_null_value_observation_does_not_500_the_route_and_matches_the_bake(tmp_path):
    """A row with value=None (a dropped sentinel) used to raise TypeError in
    ServingSnapshotRepository.get_observations — the live route 500'd for Julia Pfeiffer Burns
    on 2026-10-02. The API now skips such rows exactly as the bake does."""
    curated = tmp_path / "curated"
    _write_curated(curated)
    obs = pd.read_parquet(curated / "observations.parquet")
    newest = obs.sort_values("sample_time").iloc[[-1]].copy()
    newest["sample_time"] = _iso(pd.to_datetime(newest["sample_time"].iloc[0]).to_pydatetime() + pd.Timedelta(hours=1))
    newest["value"] = None
    pd.concat([obs, newest], ignore_index=True).to_parquet(curated / "observations.parquet", index=False)
    tides, _ = _tides_frame()
    tides.to_parquet(curated / "tides.parquet", index=False)
    build_serving_snapshot(curated)
    out = tmp_path / "bake"
    bake.bake(curated, out, with_details=True)
    service = BeachService(build_repository(Settings(curated_dir=curated, preferred_repository="serving")))
    bid = str(newest["beach_id"].iloc[0])
    api = service.get_observations(bid)  # must not raise
    assert all(o.value is not None for o in api.observations)
    baked = ObservationResponse.model_validate(
        json.loads((out / "api" / "beach" / f"{bid}.json").read_text())["observations"]
    )
    assert baked.observations[: len(api.observations)] == api.observations
