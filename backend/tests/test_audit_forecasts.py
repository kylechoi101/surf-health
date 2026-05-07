"""Tests for scripts.audit_forecasts_vs_advisories.

The audit script gates public release on the *acute* advisory pool only.
Chronic (1m-1y) and stale (>1y) pools are reported but ungated, because the
majority of real-world "active" advisories in California's beach feed are
multi-year administrative postings the model cannot predict from environmental
covariates.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audit_forecasts_vs_advisories import (  # noqa: E402
    _apply_public_release_gate,
    _build_active_pool_lookup,
    _classify_pool,
    _gate_decision,
    run_audit,
)


def _write_curated(tmp_path: Path, *, forecasts: pd.DataFrame, advisories: pd.DataFrame) -> Path:
    curated = tmp_path / "curated"
    curated.mkdir()
    forecasts.to_parquet(curated / "forecasts.parquet", index=False)
    advisories.to_parquet(curated / "advisories.parquet", index=False)
    return curated


def test_classify_pool_uses_duration_thresholds():
    assert _classify_pool(0) == "acute"
    assert _classify_pool(14) == "acute"
    assert _classify_pool(15) == "chronic"
    assert _classify_pool(365) == "chronic"
    assert _classify_pool(366) == "stale"
    assert _classify_pool(2000) == "stale"


def test_classify_pool_does_not_promote_stale_postings_by_cause_keyword():
    """A 4-year-old admin posting with cause "Sewage Spill" must remain stale.

    The CalState BRD feed contains many decade-old "Sewage Spill" advisories
    that were issued and never lifted (Tijuana plume, etc). Cause-based
    promotion to acute would mis-attribute these as model misses.
    """
    assert _classify_pool(2000, "Sewage Spill") == "stale"
    assert _classify_pool(800, "Combined Sewer Overflow") == "stale"
    assert _classify_pool(120, "Rain") == "chronic"


def test_build_active_pool_lookup_picks_strictest_pool_per_beach():
    now = pd.Timestamp("2026-05-06", tz="UTC")
    advisories = pd.DataFrame([
        # Beach A: 5-year stale Bacterial Standards Violation AND a 5-day-old sewage spill.
        # The recent sewage spill makes it acute (by duration alone, no cause needed).
        {"beach_id": "A", "status": "active", "started_at": "2021-01-01", "ended_at": None,
         "advisory_type": "Posting", "cause": "Bacterial Standards Violation"},
        {"beach_id": "A", "status": "active", "started_at": "2026-05-01", "ended_at": None,
         "advisory_type": "Closure", "cause": "Sewage Spill"},
        # Beach B: a single chronic posting (60 days old).
        {"beach_id": "B", "status": "active", "started_at": "2026-03-01", "ended_at": None,
         "advisory_type": "Posting", "cause": "Bacterial Standards Violation"},
        # Beach C: a stale 4-year posting only.
        {"beach_id": "C", "status": "active", "started_at": "2022-01-01", "ended_at": None,
         "advisory_type": "Posting", "cause": "Other"},
        # Inactive advisories must be ignored.
        {"beach_id": "D", "status": "historical", "started_at": "2026-04-01", "ended_at": "2026-04-15",
         "advisory_type": "Posting", "cause": "Sewage Spill"},
    ])

    lookup = _build_active_pool_lookup(advisories, now=now)
    by_beach = lookup.set_index("beach_id")["pool"].to_dict()

    assert by_beach == {"A": "acute", "B": "chronic", "C": "stale"}


def test_run_audit_decomposes_pools_and_blocks_when_acute_agreement_low(tmp_path: Path):
    now = pd.Timestamp("2026-05-06", tz="UTC")
    advisories = pd.DataFrame([
        # 5 acute advisories (recent sewage spills / rain). 1 model-flagged High = 0.20 agreement.
        *[
            {"beach_id": f"acute_{i}", "status": "active",
             "started_at": "2026-05-01", "ended_at": None,
             "advisory_type": "Closure", "cause": "Sewage Spill"}
            for i in range(5)
        ],
        # 4 chronic advisories: irrelevant for gate. Model flags 0 of them.
        *[
            {"beach_id": f"chronic_{i}", "status": "active",
             "started_at": "2026-01-01", "ended_at": None,
             "advisory_type": "Posting", "cause": "Bacterial Standards Violation"}
            for i in range(4)
        ],
        # 6 stale advisories: irrelevant for gate.
        *[
            {"beach_id": f"stale_{i}", "status": "active",
             "started_at": "2018-01-01", "ended_at": None,
             "advisory_type": "Posting", "cause": "Other"}
            for i in range(6)
        ],
    ])

    forecast_rows = []
    # 5 acute beaches: only acute_0 flagged.
    for i in range(5):
        forecast_rows.append({
            "beach_id": f"acute_{i}",
            "forecast_date": "2026-05-06",
            "p_exceed": 0.85 if i == 0 else 0.05,
            "risk_band": "Very High" if i == 0 else "Low",
            "model_version": "test-model-v0",
        })
    for i in range(4):
        forecast_rows.append({
            "beach_id": f"chronic_{i}",
            "forecast_date": "2026-05-06",
            "p_exceed": 0.05,
            "risk_band": "Low",
            "model_version": "test-model-v0",
        })
    for i in range(6):
        forecast_rows.append({
            "beach_id": f"stale_{i}",
            "forecast_date": "2026-05-06",
            "p_exceed": 0.05,
            "risk_band": "Low",
            "model_version": "test-model-v0",
        })
    # An unrelated false-positive: no advisory but model says Very High.
    forecast_rows.append({
        "beach_id": "unrelated_fp",
        "forecast_date": "2026-05-06",
        "p_exceed": 0.95,
        "risk_band": "Very High",
        "model_version": "test-model-v0",
    })

    forecasts = pd.DataFrame(forecast_rows)
    curated = _write_curated(tmp_path, forecasts=forecasts, advisories=advisories)

    audit = run_audit(curated, now=now)

    assert audit["pool_metrics"]["acute"]["advised_beaches"] == 5
    assert audit["pool_metrics"]["acute"]["agreement_rate"] == pytest.approx(0.2)
    assert audit["pool_metrics"]["chronic"]["advised_beaches"] == 4
    assert audit["pool_metrics"]["chronic"]["agreement_rate"] == pytest.approx(0.0)
    assert audit["pool_metrics"]["stale"]["advised_beaches"] == 6
    assert audit["false_negatives"]["by_pool"] == {
        "acute": 4, "chronic": 4, "stale": 6, "unknown_duration": 0,
    }
    assert audit["false_positives"]["count"] == 1

    # Gate should fail because acute agreement (0.2) < 0.5 with >=3 advised acute beaches.
    eligible, blocker = _gate_decision(audit)
    assert not eligible
    assert "Acute advisory agreement" in (blocker or "")


def test_run_audit_passes_gate_when_acute_agreement_high(tmp_path: Path):
    now = pd.Timestamp("2026-05-06", tz="UTC")
    advisories = pd.DataFrame([
        *[
            {"beach_id": f"acute_{i}", "status": "active",
             "started_at": "2026-05-01", "ended_at": None,
             "advisory_type": "Closure", "cause": "Sewage Spill"}
            for i in range(4)
        ],
    ])
    # 3 of 4 acute beaches model-flagged: 0.75 agreement, gate passes.
    forecasts = pd.DataFrame([
        {"beach_id": "acute_0", "forecast_date": "2026-05-06", "p_exceed": 0.85, "risk_band": "Very High", "model_version": "v"},
        {"beach_id": "acute_1", "forecast_date": "2026-05-06", "p_exceed": 0.42, "risk_band": "High", "model_version": "v"},
        {"beach_id": "acute_2", "forecast_date": "2026-05-06", "p_exceed": 0.55, "risk_band": "High", "model_version": "v"},
        {"beach_id": "acute_3", "forecast_date": "2026-05-06", "p_exceed": 0.05, "risk_band": "Low", "model_version": "v"},
    ])
    curated = _write_curated(tmp_path, forecasts=forecasts, advisories=advisories)
    audit = run_audit(curated, now=now)
    eligible, blocker = _gate_decision(audit)
    assert eligible
    assert blocker is None


def test_gate_does_not_fail_when_acute_pool_too_small(tmp_path: Path):
    now = pd.Timestamp("2026-05-06", tz="UTC")
    # Only 2 acute advisories: too few to gate on (we require >=3 acute advised beaches).
    advisories = pd.DataFrame([
        {"beach_id": "acute_0", "status": "active",
         "started_at": "2026-05-04", "ended_at": None,
         "advisory_type": "Closure", "cause": "Sewage Spill"},
        {"beach_id": "acute_1", "status": "active",
         "started_at": "2026-05-04", "ended_at": None,
         "advisory_type": "Closure", "cause": "Sewage Spill"},
    ])
    forecasts = pd.DataFrame([
        {"beach_id": "acute_0", "forecast_date": "2026-05-06", "p_exceed": 0.05, "risk_band": "Low", "model_version": "v"},
        {"beach_id": "acute_1", "forecast_date": "2026-05-06", "p_exceed": 0.05, "risk_band": "Low", "model_version": "v"},
    ])
    curated = _write_curated(tmp_path, forecasts=forecasts, advisories=advisories)
    audit = run_audit(curated, now=now)
    eligible, blocker = _gate_decision(audit)
    assert eligible
    assert blocker is None


def test_apply_gate_replaces_old_blockers_and_does_not_duplicate(tmp_path: Path):
    now = pd.Timestamp("2026-05-06", tz="UTC")
    advisories = pd.DataFrame([
        *[
            {"beach_id": f"acute_{i}", "status": "active",
             "started_at": "2026-05-01", "ended_at": None,
             "advisory_type": "Closure", "cause": "Sewage Spill"}
            for i in range(5)
        ],
    ])
    forecasts = pd.DataFrame([
        *[
            {"beach_id": f"acute_{i}", "forecast_date": "2026-05-06",
             "p_exceed": 0.05, "risk_band": "Low", "model_version": "v"}
            for i in range(5)
        ],
    ])
    curated = _write_curated(tmp_path, forecasts=forecasts, advisories=advisories)

    # Pre-populate system_health.json with stale blockers (the bug we observed
    # in production: the prior agreement-gate blocker was appended every run).
    health_path = curated / "system_health.json"
    health_path.write_text(json.dumps({
        "model_registry": {
            "promotion_blockers": [
                "Forecast/advisory agreement gate failed: 0.209 < 0.50 (risk threshold p_exceed >= 0.30).",
                "Forecast/advisory agreement gate failed: 0.209 < 0.50 (risk threshold p_exceed >= 0.30).",
                "Some other unrelated blocker.",
            ],
        }
    }))

    audit = run_audit(curated, now=now)
    _apply_public_release_gate(curated, audit)

    payload = json.loads(health_path.read_text())
    blockers = payload["model_registry"]["promotion_blockers"]

    # Stale agreement-gate blockers must be removed.
    assert all("agreement gate failed" not in b.lower() or b.startswith("Acute") for b in blockers)
    # The new acute-pool blocker must appear at most once.
    acute_blockers = [b for b in blockers if "Acute advisory agreement" in b]
    assert len(acute_blockers) == 1
    # Unrelated blockers must be preserved.
    assert "Some other unrelated blocker." in blockers


def test_apply_gate_flips_eligible_when_acute_pool_clears(tmp_path: Path):
    now = pd.Timestamp("2026-05-06", tz="UTC")
    advisories = pd.DataFrame([
        *[
            {"beach_id": f"acute_{i}", "status": "active",
             "started_at": "2026-05-01", "ended_at": None,
             "advisory_type": "Closure", "cause": "Sewage Spill"}
            for i in range(4)
        ],
    ])
    forecasts = pd.DataFrame([
        {"beach_id": "acute_0", "forecast_date": "2026-05-06", "p_exceed": 0.85, "risk_band": "Very High", "model_version": "v"},
        {"beach_id": "acute_1", "forecast_date": "2026-05-06", "p_exceed": 0.42, "risk_band": "High", "model_version": "v"},
        {"beach_id": "acute_2", "forecast_date": "2026-05-06", "p_exceed": 0.55, "risk_band": "High", "model_version": "v"},
        {"beach_id": "acute_3", "forecast_date": "2026-05-06", "p_exceed": 0.05, "risk_band": "Low", "model_version": "v"},
    ])
    curated = _write_curated(tmp_path, forecasts=forecasts, advisories=advisories)
    health_path = curated / "system_health.json"
    health_path.write_text(json.dumps({
        "model_registry": {
            "deployment_stage": "research_prototype",
            "public_release_eligible": False,
            "promotion_blockers": [
                "Forecast/advisory agreement gate failed: 0.209 < 0.50.",
            ],
        }
    }))

    audit = run_audit(curated, now=now)
    _apply_public_release_gate(curated, audit)

    payload = json.loads(health_path.read_text())
    registry = payload["model_registry"]
    assert registry["public_release_eligible"] is True
    assert registry["deployment_stage"] != "research_prototype"
    assert all("agreement gate" not in b.lower() for b in registry["promotion_blockers"])
