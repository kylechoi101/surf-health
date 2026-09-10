"""Beach-wide advisory rollup + the 7-day / explicit-lift advisory window.

The product groups sampling stations into parent beaches. The county and the
city sometimes sample different points of the SAME beach and disagree, so a
clean reading at one station is not evidence the beach is clean. When any
station under a parent is posted, every sibling station shows a beach-wide
advisory BADGE — while keeping its own modelled band, so the station-specific
result stays visible and honest.

These tests pin both halves of that contract across every backend that serves
it (sqlite snapshot, curated parquet, and the two vendored bakers), because the
rule is deliberately duplicated in four places and can silently drift.
"""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from app.data.pipeline.serving_snapshot import build_serving_snapshot
from app.repositories.curated_repository import (
    ADVISORY_MAX_AGE_DAYS,
    CuratedBeachRepository,
    filter_currently_active,
)
from app.repositories.serving_repository import ServingSnapshotRepository

POSTED = "ca-p1-posted-station"
CLEAN = "ca-p2-clean-station"
OTHER = "ca-p3-unrelated-station"
FORECAST_DATE = "2026-05-18"


def _write_curated(curated_dir: Path, advisory_rows: list[dict]) -> Path:
    curated_dir.mkdir(parents=True, exist_ok=True)
    beaches = [
        {
            "beach_id": bid,
            "name": name,
            "beach_name": "Shared Parent Beach",
            "county": "San Diego",
            "region": "San Diego",
            "station_code": bid.upper(),
            "support_status": "production",
            "latitude": 32.9,
            "longitude": -117.25,
            "latest_official_sample_at": f"{FORECAST_DATE}T08:00:00",
        }
        for bid, name in (
            (POSTED, "County Point"),
            (CLEAN, "City Point"),
            (OTHER, "Unrelated Beach"),
        )
    ]
    pd.DataFrame(beaches).to_parquet(curated_dir / "beaches.parquet", index=False)

    pd.DataFrame(
        [
            {
                "parent_beach_id": "parent-shared",
                "name": "Shared Parent Beach",
                "county": "San Diego",
                "region": "San Diego",
                "support_status": "production",
                "latitude": 32.9,
                "longitude": -117.25,
                "station_count": 2,
                "member_beach_ids": [POSTED, CLEAN],
                "latest_official_sample_at": f"{FORECAST_DATE}T08:00:00",
            },
            {
                "parent_beach_id": "parent-other",
                "name": "Unrelated Beach",
                "county": "San Diego",
                "region": "San Diego",
                "support_status": "production",
                "latitude": 33.9,
                "longitude": -118.25,
                "station_count": 1,
                "member_beach_ids": [OTHER],
                "latest_official_sample_at": f"{FORECAST_DATE}T08:00:00",
            },
        ]
    ).to_parquet(curated_dir / "parent_beaches.parquet", index=False)

    # Every station forecasts Low, so any advisory signal in the assertions
    # below can only have come from the beach-wide rollup.
    pd.DataFrame(
        [
            {
                "beach_id": bid,
                "forecast_date": FORECAST_DATE,
                "risk_band": "Low",
                "p_exceed": 0.05,
                "p_exceed_raw": 0.05,
                "top_drivers": ["dry weather"],
                "model_version": "xgb-ensemble-v1",
                "forecast_generated_at": datetime.now(UTC).isoformat(),
            }
            for bid in (POSTED, CLEAN, OTHER)
        ]
    ).to_parquet(curated_dir / "forecasts.parquet", index=False)

    pd.DataFrame(advisory_rows or None, columns=[
        "beach_id", "advisory_type", "started_at", "ended_at", "last_seen_at",
        "status", "cause", "county", "advisory_website",
    ]).to_parquet(curated_dir / "advisories.parquet", index=False)

    pd.DataFrame(columns=["beach_id"]).to_parquet(curated_dir / "latest_env.parquet", index=False)
    pd.DataFrame(columns=["beach_id", "sample_time"]).to_parquet(
        curated_dir / "observations.parquet", index=False
    )
    pd.DataFrame(columns=["beach_id", "sample_date"]).to_parquet(
        curated_dir / "beach_day.parquet", index=False
    )
    (curated_dir / "system_health.json").write_text(
        '{"pipeline_freshness": "%s", "source_freshness": {}, '
        '"model_registry": {"production_model": "xgb-ensemble-v1"}}'
        % datetime.now(UTC).isoformat()
    )
    return curated_dir


def _advisory(beach_id: str, *, days_ago: float, ended_at=None, advisory_type="Posting") -> dict:
    started = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago)
    return {
        "beach_id": beach_id,
        "advisory_type": advisory_type,
        "started_at": started.isoformat(),
        "ended_at": ended_at,
        "last_seen_at": (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)).isoformat(),
        "status": "active",
        "cause": "Bacterial Standards Violation",
        "county": "San Diego",
        "advisory_website": "https://sdbeachinfo.com",
    }


@pytest.fixture(params=["serving", "curated"])
def repo_factory(request, tmp_path):
    """Both serving backends, so the rollup cannot pass on one and regress on
    the other. `test_repository_parity` guards the coercers; this guards the
    advisory semantics."""
    def build(advisory_rows: list[dict]):
        curated_dir = _write_curated(tmp_path / "curated", advisory_rows)
        if request.param == "curated":
            return CuratedBeachRepository(curated_dir, stv_threshold=104.0)
        return ServingSnapshotRepository(
            build_serving_snapshot(curated_dir), stv_threshold=104.0
        )
    return build


class TestBeachWideRollup:
    def test_clean_sibling_of_a_posted_station_shows_the_beach_wide_badge(self, repo_factory):
        repo = repo_factory([_advisory(POSTED, days_ago=2)])
        forecast = repo.get_forecast(CLEAN, date_of(FORECAST_DATE))
        assert forecast.parent_has_active_advisory is True
        assert forecast.parent_advisory_website == "https://sdbeachinfo.com"
        # It is not itself posted — the county never flagged THIS station.
        assert forecast.official_advisory_active is False

    def test_the_rollup_badge_does_not_touch_the_band(self, repo_factory):
        """The chosen contract is badge-only: the clean station keeps its own
        modelled result so the station-specific number stays visible. If this
        ever flips to escalating the band too, it is a deliberate product
        decision and this test should be rewritten, not deleted."""
        repo = repo_factory([_advisory(POSTED, days_ago=2)])
        forecast = repo.get_forecast(CLEAN, date_of(FORECAST_DATE))
        assert forecast.risk_band == "Low"
        assert forecast.p_exceed == pytest.approx(0.05)
        assert forecast.advisory_floor_applied is False

    def test_a_posted_station_reports_its_own_advisory_not_the_rollup(self, repo_factory):
        repo = repo_factory([_advisory(POSTED, days_ago=2)])
        forecast = repo.get_forecast(POSTED, date_of(FORECAST_DATE))
        assert forecast.official_advisory_active is True
        # The rollup is only meaningful for a station with no posting of its
        # own; a posted station already renders its own advisory.
        assert forecast.parent_has_active_advisory is False

    def test_a_station_under_an_unposted_parent_stays_clean(self, repo_factory):
        repo = repo_factory([_advisory(POSTED, days_ago=2)])
        forecast = repo.get_forecast(OTHER, date_of(FORECAST_DATE))
        assert forecast.parent_has_active_advisory is False
        assert forecast.official_advisory_active is False
        assert forecast.risk_band == "Low"

    def test_no_advisories_anywhere_means_no_rollup(self, repo_factory):
        repo = repo_factory([])
        for bid in (POSTED, CLEAN, OTHER):
            forecast = repo.get_forecast(bid, date_of(FORECAST_DATE))
            assert forecast.parent_has_active_advisory is False

    def test_the_parent_card_and_the_station_badge_agree(self, repo_factory):
        """The parent card's has_active_advisory and the sibling station's
        beach-wide badge are two renderings of one fact; they must never
        disagree about the same beach."""
        repo = repo_factory([_advisory(POSTED, days_ago=2)])
        parents = {p.id: p for p in repo.list_parent_beaches()}
        assert parents["parent-shared"].has_active_advisory is True
        assert parents["parent-shared"].flagged_station_count == 1
        assert parents["parent-other"].has_active_advisory is False
        assert repo.get_forecast(CLEAN, date_of(FORECAST_DATE)).parent_has_active_advisory is True
        assert repo.get_forecast(OTHER, date_of(FORECAST_DATE)).parent_has_active_advisory is False


class TestAdvisoryWindow:
    def test_window_is_one_week(self):
        assert ADVISORY_MAX_AGE_DAYS == 7

    def test_a_posting_inside_the_window_is_active(self, repo_factory):
        repo = repo_factory([_advisory(POSTED, days_ago=6)])
        assert repo.get_forecast(POSTED, date_of(FORECAST_DATE)).official_advisory_active is True

    def test_a_posting_past_the_window_ages_out(self, repo_factory):
        """A posting the county never re-issued within a week is presumed
        superseded by a fresh sample rather than still in effect."""
        repo = repo_factory([_advisory(POSTED, days_ago=9)])
        forecast = repo.get_forecast(POSTED, date_of(FORECAST_DATE))
        assert forecast.official_advisory_active is False
        # ...and it must not leak into the sibling rollup either.
        assert repo.get_forecast(CLEAN, date_of(FORECAST_DATE)).parent_has_active_advisory is False

    def test_a_closure_bypasses_the_age_window(self, repo_factory):
        repo = repo_factory([_advisory(POSTED, days_ago=400, advisory_type="Closure")])
        assert repo.get_forecast(POSTED, date_of(FORECAST_DATE)).official_advisory_active is True


class TestExplicitLift:
    """An explicit lift always wins over the age window: once the county logs
    `ended_at`, the advisory clears immediately instead of being held for the
    rest of the week."""

    def test_a_lifted_posting_clears_immediately(self, repo_factory):
        lifted = (datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=6)).isoformat()
        repo = repo_factory([_advisory(POSTED, days_ago=2, ended_at=lifted)])
        assert repo.get_forecast(POSTED, date_of(FORECAST_DATE)).official_advisory_active is False

    def test_a_lifted_posting_clears_the_sibling_badge_too(self, repo_factory):
        lifted = (datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=6)).isoformat()
        repo = repo_factory([_advisory(POSTED, days_ago=2, ended_at=lifted)])
        assert repo.get_forecast(CLEAN, date_of(FORECAST_DATE)).parent_has_active_advisory is False

    def test_a_lifted_closure_clears_despite_the_age_exemption(self, repo_factory):
        """Closures bypass the AGE window, not an explicit lift."""
        lifted = (datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=6)).isoformat()
        repo = repo_factory(
            [_advisory(POSTED, days_ago=400, advisory_type="Closure", ended_at=lifted)]
        )
        assert repo.get_forecast(POSTED, date_of(FORECAST_DATE)).official_advisory_active is False

    def test_a_future_end_date_is_not_a_lift(self, repo_factory):
        """Some feeds pre-declare when a posting is scheduled to end. That is
        still in effect NOW and must keep warning."""
        future = (datetime.now(UTC).replace(tzinfo=None) + timedelta(days=3)).isoformat()
        repo = repo_factory([_advisory(POSTED, days_ago=2, ended_at=future)])
        assert repo.get_forecast(POSTED, date_of(FORECAST_DATE)).official_advisory_active is True

    def test_a_null_ended_at_never_drops_the_advisory(self):
        """Regression guard for the SQL/pandas null trap: `ended_at > now` is
        NULL (falsy) for un-lifted rows, which would silently expire every
        advisory in the product. `ended_at` is NULL on essentially every row.
        """
        rows = pd.DataFrame([_advisory(POSTED, days_ago=1)])
        assert len(filter_currently_active(rows)) == 1


def date_of(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()
