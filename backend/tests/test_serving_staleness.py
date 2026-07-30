"""WS2 serve-time staleness protection.

A frozen serving snapshot must degrade HONESTLY when it ages:
- forecast rows past MAX_FORECAST_AGE_HOURS are flagged is_stale (still served);
- forecast_generated_at is never fabricated for legacy rows without it;
- advisory recency is judged as-of the snapshot's own generated_at, so posted
  advisories can't silently age OUT of a stale snapshot toward "safe".
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pandas as pd

from app.data.pipeline.serving_snapshot import build_serving_snapshot
from app.repositories.serving_repository import ServingSnapshotRepository
from app.schemas.domain import MAX_FORECAST_AGE_HOURS

BEACH_ID = "ca123-orange-stale-beach-stale-beach-pier"


def _write_curated(
    curated_dir,
    *,
    forecast_date: str,
    generated_at: str | None,
    advisory_started_at: str | None = None,
    advisory_last_seen_at: str | None = None,
):
    curated_dir.mkdir()

    pd.DataFrame(
        [
            {
                "beach_id": BEACH_ID,
                "name": "Stale Beach Pier",
                "county": "Orange",
                "region": "Santa Ana",
                "support_status": "production",
                "latest_official_sample_at": (
                    datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)
                ).isoformat(),
                "latitude": 33.5,
                "longitude": -117.8,
            }
        ]
    ).to_parquet(curated_dir / "beaches.parquet", index=False)

    pd.DataFrame(
        columns=[
            "parent_beach_id", "name", "county", "region", "support_status",
            "latitude", "longitude", "station_count", "member_beach_ids",
            "latest_official_sample_at",
        ]
    ).to_parquet(curated_dir / "parent_beaches.parquet", index=False)

    pd.DataFrame(
        [
            {
                "beach_id": BEACH_ID,
                "forecast_date": forecast_date,
                "risk_band": "Low",
                "p_exceed": 0.08,
                "p_exceed_raw": 0.08,
                "top_drivers": ["dry weather"],
                "model_version": "xgb-ensemble-v1",
                "forecast_generated_at": generated_at,
            }
        ]
    ).to_parquet(curated_dir / "forecasts.parquet", index=False)

    pd.DataFrame(columns=["beach_id"]).to_parquet(curated_dir / "latest_env.parquet", index=False)
    pd.DataFrame(columns=["beach_id", "sample_time"]).to_parquet(
        curated_dir / "observations.parquet", index=False
    )
    pd.DataFrame(columns=["beach_id", "sample_date"]).to_parquet(
        curated_dir / "beach_day.parquet", index=False
    )

    if advisory_started_at is not None:
        pd.DataFrame(
            [
                {
                    "beach_id": BEACH_ID,
                    "advisory_type": "Posting",
                    "started_at": advisory_started_at,
                    "last_seen_at": advisory_last_seen_at,
                    "ended_at": None,
                    "status": "active",
                    "cause": "Bacterial Standards Violation",
                    "county": "Orange",
                    "advisory_website": "https://ocbeachinfo.com",
                }
            ]
        ).to_parquet(curated_dir / "advisories.parquet", index=False)
    else:
        pd.DataFrame(
            columns=[
                "beach_id", "advisory_type", "started_at", "ended_at",
                "status", "cause", "county", "advisory_website",
            ]
        ).to_parquet(curated_dir / "advisories.parquet", index=False)

    (curated_dir / "system_health.json").write_text(
        json.dumps(
            {
                "pipeline_freshness": datetime.now(UTC).isoformat(),
                "source_freshness": {},
                "model_registry": {"production_model": "xgb-ensemble-v1"},
            }
        )
    )


def _set_snapshot_generated_at(snapshot_path, generated_at_iso: str) -> None:
    """Rewind the snapshot's own bake timestamp to simulate a stale snapshot."""
    with sqlite3.connect(snapshot_path) as conn:
        conn.execute(
            "update system_health set payload = ? where key = 'serving_snapshot'",
            (json.dumps({"generated_at": generated_at_iso}),),
        )
        conn.commit()


def _repo(snapshot_path) -> ServingSnapshotRepository:
    return ServingSnapshotRepository(snapshot_path, stv_threshold=104.0)


def test_fresh_exact_date_row_is_not_stale(tmp_path):
    now = datetime.now(UTC)
    today = now.date()
    curated_dir = tmp_path / "curated"
    _write_curated(
        curated_dir,
        forecast_date=today.isoformat(),
        generated_at=(now - timedelta(hours=2)).isoformat(),
    )
    snapshot_path = build_serving_snapshot(curated_dir)

    forecast = _repo(snapshot_path).get_forecast(BEACH_ID, today)
    assert forecast.is_stale is False
    assert forecast.forecast_age_hours == 2
    assert forecast.forecast_generated_at is not None


def test_old_fallback_row_is_stale_with_correct_age(tmp_path):
    """The exact-date miss → latest-row fallback must not present a days-old
    Low band as today's answer: still served, but flagged is_stale."""
    now = datetime.now(UTC)
    today = now.date()
    curated_dir = tmp_path / "curated"
    _write_curated(
        curated_dir,
        forecast_date=(today - timedelta(days=5)).isoformat(),
        generated_at=(now - timedelta(hours=120)).isoformat(),
    )
    snapshot_path = build_serving_snapshot(curated_dir)

    forecast = _repo(snapshot_path).get_forecast(BEACH_ID, today)
    assert forecast.is_stale is True
    assert forecast.forecast_age_hours == 120
    # Degrade honestly — the record still carries band + probability.
    assert forecast.risk_band == "Low"
    assert forecast.p_exceed == 0.08


def test_exact_date_hit_with_old_generated_at_is_stale(tmp_path):
    """A baked snapshot can itself be old: an exact forecast_date hit whose
    generated_at is past the cap must also be flagged."""
    now = datetime.now(UTC)
    today = now.date()
    curated_dir = tmp_path / "curated"
    _write_curated(
        curated_dir,
        forecast_date=today.isoformat(),
        generated_at=(now - timedelta(hours=MAX_FORECAST_AGE_HOURS + 24)).isoformat(),
    )
    snapshot_path = build_serving_snapshot(curated_dir)

    forecast = _repo(snapshot_path).get_forecast(BEACH_ID, today)
    assert forecast.is_stale is True
    assert forecast.forecast_age_hours == MAX_FORECAST_AGE_HOURS + 24


def test_null_generated_at_serializes_null_and_keeps_age_none(tmp_path):
    """Legacy rows without forecast_generated_at must never get a fabricated
    timestamp: the field passes through as None/null and age stays None. An
    exact-date hit on a current row is judged off forecast_date, so it is
    not stale."""
    now = datetime.now(UTC)
    today = now.date()
    curated_dir = tmp_path / "curated"
    _write_curated(curated_dir, forecast_date=today.isoformat(), generated_at=None)
    snapshot_path = build_serving_snapshot(curated_dir)

    forecast = _repo(snapshot_path).get_forecast(BEACH_ID, today)
    assert forecast.forecast_generated_at is None
    assert forecast.forecast_age_hours is None
    assert forecast.is_stale is False
    assert forecast.model_dump(mode="json")["forecast_generated_at"] is None


def test_null_generated_at_on_fallback_row_is_stale(tmp_path):
    """Fallback row with no generated_at = unknowable provenance — flagged
    stale outright (fail toward warning), even when its forecast_date is
    within the age cap."""
    now = datetime.now(UTC)
    today = now.date()
    curated_dir = tmp_path / "curated"
    _write_curated(
        curated_dir,
        forecast_date=(today - timedelta(days=1)).isoformat(),
        generated_at=None,
    )
    snapshot_path = build_serving_snapshot(curated_dir)

    forecast = _repo(snapshot_path).get_forecast(BEACH_ID, today)
    assert forecast.forecast_generated_at is None
    assert forecast.forecast_age_hours is None
    assert forecast.is_stale is True


def test_advisory_window_is_judged_as_of_snapshot_generated_at(tmp_path):
    """The advisory recency window must anchor to the snapshot's own bake
    time. An advisory that was 10 days old when the snapshot was baked stays
    active when that snapshot is served 10 days later — instead of silently
    aging out toward 'safe' under a request-time clock."""
    now = datetime.now(UTC)
    today = now.date()
    naive_now = now.replace(tzinfo=None)
    curated_dir = tmp_path / "curated"
    _write_curated(
        curated_dir,
        forecast_date=today.isoformat(),
        generated_at=now.isoformat(),
        advisory_started_at=(naive_now - timedelta(days=20)).isoformat(),
        # Recent last_seen_at keeps the bake-time zombie auto-expire from
        # demoting the row; the serve-time window is what's under test.
        advisory_last_seen_at=(naive_now - timedelta(days=2)).isoformat(),
    )
    snapshot_path = build_serving_snapshot(curated_dir)
    _set_snapshot_generated_at(snapshot_path, (now - timedelta(days=10)).isoformat())

    repository = _repo(snapshot_path)
    assert BEACH_ID in repository._active_advisory_beach_ids()
    forecast = repository.get_forecast(BEACH_ID, today)
    # Contract change (2026-07-30): a posted station keeps the MODEL band, floored
    # to >= High so it can never read Low; the posting rides on
    # official_advisory_active rather than replacing the band.
    assert forecast.risk_band == "High"
    assert forecast.advisory_floor_applied is True
    assert forecast.official_advisory_active is True


def test_advisory_outside_window_as_of_snapshot_time_stays_aged_out(tmp_path):
    """Contrast case: judged as-of a fresh snapshot's bake time, a 20-day-old
    posting is legitimately outside the 14-day acute window."""
    now = datetime.now(UTC)
    today = now.date()
    naive_now = now.replace(tzinfo=None)
    curated_dir = tmp_path / "curated"
    _write_curated(
        curated_dir,
        forecast_date=today.isoformat(),
        generated_at=now.isoformat(),
        advisory_started_at=(naive_now - timedelta(days=20)).isoformat(),
        advisory_last_seen_at=(naive_now - timedelta(days=2)).isoformat(),
    )
    snapshot_path = build_serving_snapshot(curated_dir)

    repository = _repo(snapshot_path)
    assert BEACH_ID not in repository._active_advisory_beach_ids()
    forecast = repository.get_forecast(BEACH_ID, today)
    assert forecast.risk_band == "Low"
    assert forecast.official_advisory_active is False
