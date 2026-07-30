import json
import sqlite3
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd

from app.data.pipeline.serving_snapshot import (
    auto_expire_zombie_advisories,
    build_serving_snapshot,
)
from app.repositories.factory import build_repository
from app.repositories.serving_repository import ServingSnapshotRepository, _safe_bool


class TestSafeBool:
    def test_true_values(self):
        assert _safe_bool(True) is True
        assert _safe_bool(1) is True
        assert _safe_bool("1") is True
        assert _safe_bool("true") is True
        assert _safe_bool("True") is True
        assert _safe_bool("yes") is True

    def test_false_values(self):
        assert _safe_bool(False) is False
        assert _safe_bool(0) is False
        assert _safe_bool("0") is False
        assert _safe_bool("false") is False
        assert _safe_bool("False") is False
        assert _safe_bool("") is False

    def test_none_default_true(self):
        assert _safe_bool(None, default=True) is True

    def test_none_default_false(self):
        assert _safe_bool(None, default=False) is False


def _write_curated_inputs(curated_dir):
    curated_dir.mkdir()
    beach_id = "ca123-orange-main-beach-main-beach-pier"
    other_id = "ca999-orange-other-beach-other"

    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "name": "Main Beach Pier",
                "county": "Orange",
                "region": "Santa Ana",
                "support_status": "production",
                "latest_official_sample_at": "2026-04-18T08:00:00",
                "latitude": 33.5,
                "longitude": -117.8,
            },
            {
                "beach_id": other_id,
                "name": "Other Beach",
                "county": "Orange",
                "region": "Santa Ana",
                "support_status": "production",
                "latest_official_sample_at": "2026-04-18T08:00:00",
                "latitude": 33.6,
                "longitude": -117.9,
            },
        ]
    ).to_parquet(curated_dir / "beaches.parquet", index=False)

    pd.DataFrame(
        [
            {
                "parent_beach_id": "parent-ca123",
                "name": "Main Beach",
                "county": "Orange",
                "region": "Santa Ana",
                "support_status": "production",
                "latitude": 33.5,
                "longitude": -117.8,
                "station_count": 2,
                "member_beach_ids": [beach_id, other_id],
                "latest_official_sample_at": "2026-04-18T08:00:00",
            }
        ]
    ).to_parquet(curated_dir / "parent_beaches.parquet", index=False)

    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "forecast_date": "2026-04-20",
                "risk_band": "High",
                "p_exceed": 0.72,
                "p_exceed_raw": 0.18,
                "p_exceed_lower": 0.61,
                "p_exceed_upper": 0.84,
                "advisory_floor_applied": True,
                "predicted_log_enterococcus": 2.1,
                "lower_prediction_interval": 1.3,
                "upper_prediction_interval": 2.9,
                "prediction_interval_level": 0.9,
                "top_drivers": ["recent high sample", "waves elevated"],
                "model_version": "stacked-ensemble-curated-v0",
                "forecast_generated_at": "2026-04-20T13:00:00+00:00",
                "wave_height_m": 1.2,
                "dominant_period_s": 8.0,
                "water_temperature_c": 16.4,
                "salinity_psu": 33.1,
                "uv_index": 6.0,
            }
        ]
    ).to_parquet(curated_dir / "forecasts.parquet", index=False)

    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "wave_height_m": 1.1,
                "dominant_period_s": 8.0,
                "water_temperature_c": 16.2,
                "salinity_psu": 33.0,
                "uv_index": 5.0,
                "wind_speed_mps": 3.0,
                "wind_direction_deg": 220.0,
            }
        ]
    ).to_parquet(curated_dir / "latest_env.parquet", index=False)

    observations = []
    beach_days = []
    for idx in range(30):
        day = pd.Timestamp("2026-04-01") + pd.Timedelta(days=idx)
        observations.append(
            {
                "beach_id": beach_id,
                "sample_time": day.isoformat(),
                "sample_date": day.date().isoformat(),
                "analyte": "enterococcus",
                "method": "Culture",
                "units": "CFU/100ml",
                "value": float(20 + idx),
                "exceeds_stv": idx > 26,
                "weather": "Sunny",
                "storm_drain_flow": "No",
            }
        )
        beach_days.append(
            {
                "beach_id": beach_id,
                "sample_date": day.date().isoformat(),
                "wave_height_m": float(idx),
                "dominant_period_s": 8.0,
                "water_temperature_c": 16.0,
                "salinity_psu": 33.0,
                "weather": "Sunny",
                "storm_drain_flow": "No",
                "tidal_height": 1.0,
                "surf_height_observed": 2.0,
                "turbidity_observed": 5.0,
            }
        )
    pd.DataFrame(observations).to_parquet(curated_dir / "observations.parquet", index=False)
    pd.DataFrame(beach_days).to_parquet(curated_dir / "beach_day.parquet", index=False)

    pd.DataFrame(
        [
            {
                "beach_id": beach_id,
                "advisory_type": "Posting",
                # Dynamic recent date so this stays inside the 14-day active
                # window regardless of when the test runs.
                "started_at": (datetime.utcnow() - timedelta(days=2)).isoformat(),
                "ended_at": None,
                "status": "active",
                "cause": "Unknown Cause",
                "county": "Orange",
                "advisory_website": "https://www.ocgov.com/beach/advisory",
            }
        ]
    ).to_parquet(curated_dir / "advisories.parquet", index=False)

    (curated_dir / "system_health.json").write_text(
        json.dumps(
            {
                "pipeline_freshness": "2026-04-20T05:00:00Z",
                "source_freshness": {"observations": "2026-04-20T05:00:00Z"},
                "model_registry": {
                    "production_model": "stacked-ensemble-curated-v0",
                    "candidate_models": [],
                    "metrics": {},
                },
            }
        )
    )

    return beach_id


def test_serving_snapshot_limits_hot_path_rows_and_repository_serves_contract(tmp_path):
    curated_dir = tmp_path / "curated"
    beach_id = _write_curated_inputs(curated_dir)
    snapshot_path = build_serving_snapshot(curated_dir)

    with sqlite3.connect(snapshot_path) as conn:
        assert conn.execute("select count(*) from observations_recent").fetchone()[0] == 25
        assert conn.execute("select count(*) from recent_environment").fetchone()[0] == 10

    repository = ServingSnapshotRepository(snapshot_path, stv_threshold=104.0)

    beach = repository.get_beach(beach_id)
    assert beach.name == "Main Beach"

    forecast = repository.get_forecast(beach_id, date(2026, 4, 20))
    # Contract change (2026-07-30): a posted station keeps the MODEL band, floored
    # to >= High so it can never read Low; the posting rides on
    # official_advisory_active rather than replacing the band.
    assert forecast.risk_band == "High"
    assert forecast.advisory_floor_applied is True
    assert forecast.official_advisory_active is True
    assert forecast.model_risk_band == "Low"
    assert forecast.forecast_label_mode == "official_advisory_override"
    assert forecast.sample_age_days == 2
    assert forecast.sample_recency_band == "fresh"
    assert forecast.p_exceed == 0.72
    assert forecast.p_exceed_raw == 0.18
    assert forecast.advisory_floor_applied is True
    assert forecast.p_exceed_lower == 0.61
    assert forecast.p_exceed_upper == 0.84
    assert forecast.environmental_summary.wave_height_m == 1.2

    observations = repository.get_observations(beach_id)
    assert len(observations.observations) == 25
    assert len(observations.recent_environment) == 10
    assert observations.observations[0].value == 49.0
    assert observations.advisories[0].advisory_website == "https://www.ocgov.com/beach/advisory"

    parents = repository.list_parent_beaches()
    # Parent contract (2026-07-30): the advisory rides on has_active_advisory --
    # an OR across members, so ANY posted member flags the parent (deliberate) --
    # while risk_band is the worst MODEL band among members, so each area still
    # shows its own modelled result. The posted member is floored to >= High
    # individually, so it cannot drag the parent below High either.
    assert parents[0].has_active_advisory is True
    assert parents[0].risk_band == "High"

    health = repository.get_system_health()
    assert health.is_beta_product is True
    assert health.active_advisories_count == 1
    assert health.repository_mode == "sqlite"


class TestAutoExpireZombieAdvisories:
    """G.2: 14-day auto-expire of stuck 'active' advisories."""

    def _frame(self, rows):
        return pd.DataFrame(rows)

    def test_expires_active_older_than_14_days(self):
        df = self._frame([
            {
                "beach_id": "ca-zombie",
                "advisory_type": "Posting",
                "status": "active",
                "started_at": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30),
            }
        ])
        out, n = auto_expire_zombie_advisories(df)
        assert n == 1
        assert (out["status"] == "historical").all()

    def test_keeps_fresh_active(self):
        df = self._frame([
            {
                "beach_id": "ca-fresh",
                "advisory_type": "Posting",
                "status": "active",
                "started_at": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=2),
            }
        ])
        out, n = auto_expire_zombie_advisories(df)
        assert n == 0
        assert (out["status"] == "active").all()

    def test_keeps_chronic_posting_even_when_stale(self):
        """Chronic Postings (Sonoma's documented chronic sites etc) are
        intentionally left open by counties — must NOT be auto-expired."""
        df = self._frame([
            {
                "beach_id": "ca-chronic",
                "advisory_type": "Chronic Posting",
                "status": "active",
                "started_at": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=500),
            }
        ])
        out, n = auto_expire_zombie_advisories(df)
        assert n == 0
        assert (out["status"] == "active").all()

    def test_prefers_last_seen_at_over_started_at(self):
        """If we have a last_seen_at (e.g. county scraper saw it yesterday)
        the auto-expire must use that fresher timestamp instead of the
        stale started_at."""
        df = self._frame([
            {
                "beach_id": "ca-recently-seen",
                "advisory_type": "Posting",
                "status": "active",
                "started_at": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=200),
                "last_seen_at": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=3),
            }
        ])
        out, n = auto_expire_zombie_advisories(df)
        assert n == 0
        assert (out["status"] == "active").all()

    def test_mixed_input(self):
        now = pd.Timestamp.now(tz="UTC")
        df = self._frame([
            {"beach_id": "ca-1", "advisory_type": "Posting", "status": "active",
             "started_at": now - pd.Timedelta(days=2)},
            {"beach_id": "ca-2", "advisory_type": "Posting", "status": "active",
             "started_at": now - pd.Timedelta(days=60)},
            {"beach_id": "ca-3", "advisory_type": "Chronic Posting", "status": "active",
             "started_at": now - pd.Timedelta(days=60)},
            {"beach_id": "ca-4", "advisory_type": "Posting", "status": "historical",
             "started_at": now - pd.Timedelta(days=400)},
        ])
        out, n = auto_expire_zombie_advisories(df)
        assert n == 1  # only ca-2 should flip; chronic and historical are skipped
        statuses = dict(zip(out["beach_id"], out["status"]))
        assert statuses["ca-1"] == "active"
        assert statuses["ca-2"] == "historical"
        assert statuses["ca-3"] == "active"  # chronic untouched
        assert statuses["ca-4"] == "historical"  # already historical, unchanged

    def test_handles_empty_frame(self):
        out, n = auto_expire_zombie_advisories(pd.DataFrame())
        assert n == 0
        assert out.empty


def test_repository_factory_prefers_serving_snapshot_when_present(tmp_path):
    curated_dir = tmp_path / "curated"
    _write_curated_inputs(curated_dir)
    build_serving_snapshot(curated_dir)
    for parquet_path in curated_dir.glob("*.parquet"):
        parquet_path.unlink()

    settings = SimpleNamespace(
        curated_dir=curated_dir,
        preferred_repository="curated",
        fixture_data_path=tmp_path / "missing.json",
        epa_marine_enterococcus_stv=104.0,
    )

    repository = build_repository(settings)

    assert isinstance(repository, ServingSnapshotRepository)


def _write_multi_member_parent(curated_dir):
    """Build a parent with 4 member stations; 2 are posted, 2 aren't.
    Used to pin down the H spec — ParentBeachSummary.flagged_station_count.
    """
    curated_dir.mkdir()
    beach_ids = [
        "ca100-orange-multi-member-station-1",
        "ca101-orange-multi-member-station-2",
        "ca102-orange-multi-member-station-3",
        "ca103-orange-multi-member-station-4",
    ]
    nicknames = ["Black's Beach", "North Stairs", "South Stairs", "Pier Cove"]
    codes = ["FM-090", "NS-01", "SS-02", "PC-03"]
    rows = []
    for bid, nick, code in zip(beach_ids, nicknames, codes):
        rows.append({
            "beach_id": bid,
            "name": nick,
            "station_code": code,
            "county": "Orange",
            "region": "Santa Ana",
            "support_status": "production",
            "latest_official_sample_at": "2026-05-18T08:00:00",
            "latitude": 33.5,
            "longitude": -117.8,
        })
    pd.DataFrame(rows).to_parquet(curated_dir / "beaches.parquet", index=False)

    pd.DataFrame(
        [
            {
                "parent_beach_id": "parent-ca100",
                "name": "Torrey Pines State Beach",
                "county": "Orange",
                "region": "Santa Ana",
                "support_status": "production",
                "latitude": 33.5,
                "longitude": -117.8,
                "station_count": 4,
                "member_beach_ids": beach_ids,
                "latest_official_sample_at": "2026-05-18T08:00:00",
            }
        ]
    ).to_parquet(curated_dir / "parent_beaches.parquet", index=False)

    pd.DataFrame(
        [
            {
                "beach_id": beach_ids[0],
                "forecast_date": "2026-05-18",
                "risk_band": "Low",
                "p_exceed": 0.10,
                "model_version": "hist-gbm-v0",
                "forecast_generated_at": "2026-05-18T13:00:00+00:00",
            }
        ]
    ).to_parquet(curated_dir / "forecasts.parquet", index=False)

    pd.DataFrame(columns=["beach_id"]).to_parquet(curated_dir / "latest_env.parquet", index=False)
    pd.DataFrame(columns=["beach_id", "sample_time"]).to_parquet(curated_dir / "observations.parquet", index=False)
    pd.DataFrame(columns=["beach_id", "sample_date"]).to_parquet(curated_dir / "beach_day.parquet", index=False)

    now_iso = (datetime.utcnow() - timedelta(days=2)).isoformat()
    pd.DataFrame(
        [
            {
                "beach_id": beach_ids[0],
                "advisory_type": "Posting",
                "started_at": now_iso,
                "ended_at": None,
                "status": "active",
                "cause": "Bacterial Standards Violation",
                "county": "Orange",
                "advisory_website": "https://ocbeachinfo.com",
            },
            {
                "beach_id": beach_ids[2],
                "advisory_type": "Closure",
                "started_at": now_iso,
                "ended_at": None,
                "status": "active",
                "cause": "Sewage Spill",
                "county": "Orange",
                "advisory_website": "https://ocbeachinfo.com",
            },
        ]
    ).to_parquet(curated_dir / "advisories.parquet", index=False)

    (curated_dir / "system_health.json").write_text(
        json.dumps(
            {
                "pipeline_freshness": "2026-05-18T05:00:00Z",
                "source_freshness": {"observations": "2026-05-18T05:00:00Z"},
                "model_registry": {
                    "production_model": "hist-gbm-v0",
                    "candidate_models": [],
                    "metrics": {},
                },
            }
        )
    )
    return beach_ids, nicknames


def test_serving_parent_beach_flags_member_stations(tmp_path):
    """H: a parent with 4 members and 2 active advisories must report
    flagged_station_count=2 and the two correct names."""
    curated_dir = tmp_path / "curated"
    beach_ids, nicknames = _write_multi_member_parent(curated_dir)
    snapshot_path = build_serving_snapshot(curated_dir)

    repository = ServingSnapshotRepository(snapshot_path, stv_threshold=104.0)
    parents = repository.list_parent_beaches()
    assert len(parents) == 1
    p = parents[0]
    assert p.station_count == 4
    assert p.has_active_advisory is True
    assert p.flagged_station_count == 2
    # The two posted members are index 0 (Black's Beach) and index 2 (South Stairs).
    assert set(p.flagged_station_names) == {nicknames[0], nicknames[2]}


def test_serving_parent_exposes_member_station_codes(tmp_path):
    """Each parent carries the Beachwatch station code for every member,
    index-aligned with member_beach_ids so the apps can render a compact
    station-code chip for the resolved display station."""
    curated_dir = tmp_path / "curated"
    beach_ids, _ = _write_multi_member_parent(curated_dir)
    snapshot_path = build_serving_snapshot(curated_dir)

    repository = ServingSnapshotRepository(snapshot_path, stv_threshold=104.0)
    parents = repository.list_parent_beaches()
    p = parents[0]
    assert p.member_beach_ids == beach_ids
    assert p.member_station_codes == ["FM-090", "NS-01", "SS-02", "PC-03"]


def test_serving_beach_exposes_station_code(tmp_path):
    """A single BeachSummary carries its Beachwatch station code."""
    curated_dir = tmp_path / "curated"
    beach_ids, _ = _write_multi_member_parent(curated_dir)
    snapshot_path = build_serving_snapshot(curated_dir)

    repository = ServingSnapshotRepository(snapshot_path, stv_threshold=104.0)
    by_id = {b.id: b for b in repository.list_beaches()}
    assert by_id[beach_ids[0]].station_code == "FM-090"
    assert by_id[beach_ids[2]].station_code == "SS-02"


def test_serving_parent_with_no_advisories_reports_zero_flagged(tmp_path):
    curated_dir = tmp_path / "curated"
    _write_curated_inputs(curated_dir)
    # Drop the advisory so this parent has none.
    pd.DataFrame(
        columns=[
            "beach_id", "advisory_type", "started_at", "ended_at",
            "status", "cause", "county", "advisory_website",
        ]
    ).to_parquet(curated_dir / "advisories.parquet", index=False)

    snapshot_path = build_serving_snapshot(curated_dir)
    repository = ServingSnapshotRepository(snapshot_path, stv_threshold=104.0)
    parents = repository.list_parent_beaches()
    assert len(parents) == 1
    p = parents[0]
    assert p.has_active_advisory is False
    assert p.flagged_station_count == 0
    assert p.flagged_station_names == []
