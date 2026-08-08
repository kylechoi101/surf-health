"""Guard the vendored risk-band logic in ``scripts/bake_web_static.py``.

``bake_web_static.py`` runs in the *web* repo's CI with no surf_health backend
deps installed, so it intentionally VENDORS (re-declares) the risk-band
thresholds + ``risk_band()`` instead of importing them from
``app.ml.calibration``. That vendoring can silently drift if someone re-tunes
the canonical cutpoints and forgets the copy. These tests fail CI on drift
(FIX #36) and lock in the None/NaN-aware raw-probability selection so a genuine
``p_exceed_raw`` of exactly 0.0 is no longer mislabelled via a truthiness ``or``
(FIX #37).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.ml import calibration as canon
from scripts import bake_web_static as bake


# Every band boundary (and the values straddling it) so a missed cutpoint edit
# in either copy is caught.
_BAND_SWEEP = [
    0.0,
    0.1,
    0.19,
    0.20,
    0.25,
    0.29,
    0.30,
    0.5,
    0.69,
    0.70,
    0.85,
    1.0,
]


def test_vendored_thresholds_match_canonical():
    """FIX #36: each vendored threshold == its calibration.py counterpart."""
    assert bake._LOW_THRESHOLD == canon._LOW_THRESHOLD
    assert bake._HIGH_THRESHOLD == canon._HIGH_THRESHOLD
    assert bake._VERY_HIGH_THRESHOLD == canon._VERY_HIGH_THRESHOLD


def test_vendored_risk_band_matches_canonical_across_boundaries():
    """FIX #36: vendored risk_band() returns the same label as the canonical one
    across every band boundary."""
    for p in _BAND_SWEEP:
        assert bake.risk_band(p) == canon.risk_band(p), f"divergence at p={p}"


def test_zero_raw_probability_yields_low_not_high():
    """FIX #37: a genuine p_exceed_raw of exactly 0.0 under an active advisory
    must produce model_risk_band 'Low' (from 0.0), NOT 'High' (from the
    advisory-floored served p_exceed of 0.30). A truthiness ``or`` regressed
    this by letting 0.0 fall through to p_exceed."""
    fc_row = pd.Series(
        {
            "beach_id": "b1",
            "p_exceed_raw": 0.0,
            "p_exceed": 0.30,
            "risk_band": "Advisory",
        }
    )
    block = bake._build_forecast_block(fc_row, has_active_advisory=True)
    assert block["official_advisory_active"] is True
    # FIX #37's invariant, unchanged: model_risk_band comes from the REAL raw 0.0,
    # never from the advisory-floored served value.
    assert block["model_risk_band"] == "Low"
    # Contract change (2026-07-30): risk_band is no longer replaced by a synthetic
    # "Advisory" band. It is the model's band computed from the advisory-FLOORED
    # probability, so a posted beach reads High rather than Low while the posting
    # itself is carried by official_advisory_active.
    assert block["risk_band"] == "High"
    assert block["p_exceed"] == canon._HIGH_THRESHOLD
    assert block["advisory_floor_applied"] is True


def test_raw_probability_preferred_over_floored_served_value():
    """A finite raw probability is always used in preference to the floored
    served p_exceed, regardless of magnitude."""
    fc_row = pd.Series(
        {"beach_id": "b2", "p_exceed_raw": 0.05, "p_exceed": 0.30}
    )
    block = bake._build_forecast_block(fc_row, has_active_advisory=True)
    assert block["model_risk_band"] == "Low"  # from 0.05, not 0.30


def test_missing_raw_falls_back_to_served_value():
    """When p_exceed_raw is absent/NaN, fall back to p_exceed."""
    fc_row = pd.Series(
        {"beach_id": "b3", "p_exceed_raw": float("nan"), "p_exceed": 0.30}
    )
    block = bake._build_forecast_block(fc_row, has_active_advisory=True)
    assert block["model_risk_band"] == "High"  # from the 0.30 fallback


def test_no_advisory_clears_model_band():
    """Without an active advisory the served band is the model band and
    model_risk_band is None (mirrors the repository override logic)."""
    fc_row = pd.Series(
        {"beach_id": "b4", "p_exceed_raw": 0.0, "p_exceed": 0.30}
    )
    block = bake._build_forecast_block(fc_row, has_active_advisory=False)
    assert block["official_advisory_active"] is False
    assert block["model_risk_band"] is None


def _write_min_curated(curated: Path, parent_beaches: pd.DataFrame) -> None:
    """Write the minimal curated parquets bake() reads, plus a caller-supplied
    parent_beaches frame."""
    beaches = pd.DataFrame(
        [
            {
                "beach_id": "ca999-north-a", "name": "Spot A", "beach_name": "Big Beach",
                "station_code": "AA-1", "county": "Test", "region": "RB1",
                "latitude": 34.0, "longitude": -119.0, "support_status": "production",
                "water_body_type": "Open Coast",
            },
            {
                "beach_id": "ca999-south-b", "name": "Spot B", "beach_name": "Big Beach",
                "station_code": "BB-2", "county": "Test", "region": "RB1",
                "latitude": 33.9, "longitude": -119.0, "support_status": "beta",
                "water_body_type": "Open Coast",
            },
        ]
    )
    beaches.to_parquet(curated / "beaches.parquet", index=False)
    pd.DataFrame(
        [{"beach_id": "ca999-north-a", "p_exceed_raw": 0.05, "p_exceed": 0.05,
          "risk_band": "Low", "top_drivers": []}]
    ).to_parquet(curated / "forecasts.parquet", index=False)
    pd.DataFrame(
        columns=["beach_id", "status", "started_at", "advisory_type", "advisory_website"]
    ).to_parquet(curated / "advisories.parquet", index=False)
    parent_beaches.to_parquet(curated / "parent_beaches.parquet", index=False)


def test_parent_ids_come_from_parquet_not_prefix(tmp_path):
    """Regression for the La Jolla "down" bug: the bake MUST emit the parent
    ids from parent_beaches.parquet (the API's geographic sub-cluster split),
    NOT a re-derived beach_id-prefix grouping. Otherwise the directory's live
    API refresh links to split-parent pages (parent-...-1/-2) that the static
    export never generated -> 404."""
    curated = tmp_path / "curated"
    curated.mkdir()
    out = tmp_path / "out"
    # usepa_id ca999 split into North/South sub-clusters by the pipeline.
    parents = pd.DataFrame(
        [
            {
                "parent_beach_id": "parent-ca999-1", "usepa_id": "ca999",
                "name": "Big Beach \u00b7 North", "county": "Test", "region": "RB1",
                "support_status": "production", "latitude": 34.0, "longitude": -119.0,
                "station_count": 1, "member_beach_ids": ["ca999-north-a"],
                "latest_official_sample_at": None,
            },
            {
                "parent_beach_id": "parent-ca999-2", "usepa_id": "ca999",
                "name": "Big Beach \u00b7 South", "county": "Test", "region": "RB1",
                "support_status": "beta", "latitude": 33.9, "longitude": -119.0,
                "station_count": 1, "member_beach_ids": ["ca999-south-b"],
                "latest_official_sample_at": None,
            },
        ]
    )
    _write_min_curated(curated, parents)

    bake.bake(curated, out)
    baked = json.loads((out / "parent_beaches.json").read_text())
    ids = {p["id"] for p in baked}

    # The split ids from the parquet must be present...
    assert "parent-ca999-1" in ids
    assert "parent-ca999-2" in ids
    # ...and the collapsed prefix id must NOT (that was the 404 bug).
    assert "parent-ca999" not in ids

    north = next(p for p in baked if p["id"] == "parent-ca999-1")
    assert north["member_beach_ids"] == ["ca999-north-a"]
    assert north["member_station_codes"] == ["AA-1"]
    assert north["risk_band"] == "Low"  # rolled up from the member forecast


def test_parent_fallback_when_parquet_missing(tmp_path):
    """Without parent_beaches.parquet the bake degrades to prefix grouping
    (kept so the bake never hard-fails) instead of crashing."""
    curated = tmp_path / "curated"
    curated.mkdir()
    out = tmp_path / "out"
    parents = pd.DataFrame(
        [{"parent_beach_id": "parent-ca999-1", "usepa_id": "ca999", "name": "x",
          "county": "Test", "region": "RB1", "support_status": "production",
          "latitude": 34.0, "longitude": -119.0, "station_count": 1,
          "member_beach_ids": ["ca999-north-a"], "latest_official_sample_at": None}]
    )
    _write_min_curated(curated, parents)
    (curated / "parent_beaches.parquet").unlink()  # force the fallback path

    bake.bake(curated, out)
    baked = json.loads((out / "parent_beaches.json").read_text())
    assert len(baked) >= 1  # produced *something* rather than crashing


def test_posted_beach_can_never_render_low_or_moderate():
    """The safety guarantee that makes dropping the "Advisory" band acceptable.

    risk_band is now the model's own band on a posted beach, so the ONLY thing
    stopping a posting from being displayed as "Low" is the advisory floor. Before
    it was wired to the same flag that raises the badge, the pipeline's
    feature-driven floor missed 2 of 18 posted beaches on the shipped bake (Gazos
    Creek Access p=0.056, Keller Beach p=0.118) -- both would have read "Low"
    beside an ADVISORY badge. Sweep the whole probability range: no input may
    produce Low or Moderate while a posting is active.
    """
    # Sweep values STRICTLY BELOW the floor -- these are the ones it must lift.
    # Bounds track _HIGH_THRESHOLD, which the 2026-08-08 band reset moved
    # 0.30 -> 0.20; 0.20 and 0.29999 therefore graduated to the untouched sweep.
    for raw in (0.0, 0.001, 0.05609, 0.11764, 0.19, 0.199999):
        row = pd.Series({"beach_id": "b", "p_exceed_raw": raw, "p_exceed": raw})
        block = bake._build_forecast_block(row, has_active_advisory=True)
        assert block["risk_band"] not in ("Low", "Moderate"), f"raw={raw} -> {block['risk_band']}"
        assert block["p_exceed"] >= canon._HIGH_THRESHOLD
        assert block["advisory_floor_applied"] is True
    # At or above the cutpoint the genuine probability must survive untouched --
    # and must still never read Low or Moderate, which is the actual guarantee.
    for raw in (0.20, 0.29999, 0.30, 0.5045, 0.99):
        row = pd.Series({"beach_id": "b", "p_exceed_raw": raw, "p_exceed": raw})
        block = bake._build_forecast_block(row, has_active_advisory=True)
        assert block["p_exceed"] == raw
        assert block["advisory_floor_applied"] is False
        assert block["risk_band"] not in ("Low", "Moderate"), f"raw={raw} -> {block['risk_band']}"
    # And an unposted beach is never floored. (The unposted path passes risk_band
    # through from the parquet row rather than recomputing it, so the fixture
    # supplies it the way the real forecasts.parquet does.)
    row = pd.Series(
        {"beach_id": "b", "p_exceed_raw": 0.02, "p_exceed": 0.02, "risk_band": "Low"}
    )
    block = bake._build_forecast_block(row, has_active_advisory=False)
    assert block["risk_band"] == "Low"
    assert block["p_exceed"] == 0.02
    assert block["official_advisory_active"] is False


def test_display_and_feature_advisory_gates_are_different_questions():
    """Why forecasts.parquet needed its own floor fix (2026-07-30).

    Two advisory gates coexist and legitimately disagree:
      * MODEL feature ``advisory_active_recent_for_floor`` -- "active AND started
        within 365d, or Tijuana River" -- deliberately excludes stale bookkeeping
        advisories so they don't pollute a training feature.
      * DISPLAY authority ``filter_currently_active`` -- "closure, OR posted within
        14d" -- which is what raises the badge users see.

    training._export_forecasts floored on the feature gate alone, so when only the
    display gate fired the parquet shipped Low/Moderate for a posted beach while
    every read path (API + web bake) floored it to High. Users were safe, but the
    artifact at rest -- and forecast_history, and the served_metrics scored from it
    -- disagreed with what was actually served. Measured that day: 5 such beaches.

    This pins the policies as genuinely distinct, so a future edit that "unifies"
    them by deleting one has to do so deliberately.
    """
    from app.repositories.curated_repository import filter_currently_active

    now = pd.Timestamp.now(tz="UTC")
    advisories = pd.DataFrame(
        [
            # Posted 3 days ago: BOTH gates fire.
            {"beach_id": "recent", "status": "active", "advisory_type": "posting",
             "started_at": now - pd.Timedelta(days=3)},
            # A closure with no recent start: the display gate fires (closures are
            # never age-gated); the 365d feature gate would not.
            {"beach_id": "old-closure", "status": "active", "advisory_type": "closure",
             "started_at": now - pd.Timedelta(days=800)},
            # Lifted: neither fires.
            {"beach_id": "inactive", "status": "inactive", "advisory_type": "posting",
             "started_at": now - pd.Timedelta(days=1)},
        ]
    )
    display_active = set(filter_currently_active(advisories)["beach_id"])
    assert "recent" in display_active
    assert "old-closure" in display_active, "closures are never age-gated for display"
    assert "inactive" not in display_active

    # And the floor must lift any of them out of Low/Moderate once it fires.
    for raw in (0.0, 0.1245, 0.2216, 0.29999):
        row = pd.Series({"beach_id": "b", "p_exceed_raw": raw, "p_exceed": raw})
        block = bake._build_forecast_block(row, has_active_advisory=True)
        assert block["risk_band"] not in ("Low", "Moderate")
        assert block["p_exceed"] >= canon._HIGH_THRESHOLD
