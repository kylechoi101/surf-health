"""Release-gate publication blocking + verify_release_gate.py CI script.

Covers PART B of the public-readiness hardening: with enforcement on and an
ineligible promotion assessment, forecasts.parquet is NOT overwritten (the
last-validated forecast keeps serving); and the verify_release_gate.py script
exits 0/1 with the blockers printed.
"""

from __future__ import annotations

import json

import pandas as pd

from app.ml.training import (
    _promotion_assessment,
    _publish_forecasts_unless_blocked,
)
from scripts import verify_release_gate as vrg


def _sentinel_forecasts(curated_dir, marker: str) -> None:
    pd.DataFrame({"beach_id": ["b1"], "risk_band": [marker], "p_exceed": [0.1]}).to_parquet(
        curated_dir / "forecasts.parquet", index=False
    )


def _ineligible_metrics() -> dict:
    # No spatial_* keys at all -> _promotion_assessment blocks on missing spatial
    # holdout validation. Production test metric present so the first gate passes.
    return {"hist_gbm": {"aucpr": 0.6, "brier": 0.1}}


def _eligible_metrics() -> dict:
    return {
        "hist_gbm": {"aucpr": 0.6, "brier": 0.1},
        "spatial_county_persistence": {"aucpr": 0.40, "brier": 0.18},
        "spatial_beach_persistence": {"aucpr": 0.63, "brier": 0.22},
        "spatial_county_hist_gbm": {"aucpr": 0.55, "brier": 0.12, "calibration_slope": 1.0},
        "spatial_beach_hist_gbm": {"aucpr": 0.86, "brier": 0.14, "calibration_slope": 1.1},
    }


def test_enforced_gate_does_not_overwrite_forecasts_when_ineligible(tmp_path):
    _sentinel_forecasts(tmp_path, "PREVIOUS")
    promotion = _promotion_assessment(_ineligible_metrics(), "hist_gbm")
    assert promotion["public_release_eligible"] is False

    release_blocked = True and not promotion["public_release_eligible"]
    wrote = _publish_forecasts_unless_blocked(
        tmp_path,
        [{"beach_id": "b1", "risk_band": "FRESH", "p_exceed": 0.9}],
        release_blocked=release_blocked,
        blockers=promotion["promotion_blockers"],
    )
    assert wrote is False
    # The previous forecast is untouched on disk.
    on_disk = pd.read_parquet(tmp_path / "forecasts.parquet")
    assert list(on_disk["risk_band"]) == ["PREVIOUS"]


def test_enforced_gate_writes_forecasts_when_eligible(tmp_path):
    _sentinel_forecasts(tmp_path, "PREVIOUS")
    promotion = _promotion_assessment(_eligible_metrics(), "hist_gbm")
    assert promotion["public_release_eligible"] is True

    release_blocked = True and not promotion["public_release_eligible"]
    wrote = _publish_forecasts_unless_blocked(
        tmp_path,
        [{"beach_id": "b1", "risk_band": "FRESH", "p_exceed": 0.9}],
        release_blocked=release_blocked,
        blockers=promotion["promotion_blockers"],
    )
    assert wrote is True
    on_disk = pd.read_parquet(tmp_path / "forecasts.parquet")
    assert list(on_disk["risk_band"]) == ["FRESH"]


def test_publish_helper_skips_when_blocked_without_prior_file(tmp_path):
    # No prior file at all: a blocked run simply writes nothing (no crash, no file).
    wrote = _publish_forecasts_unless_blocked(
        tmp_path, [{"beach_id": "b1"}], release_blocked=True, blockers=["x"]
    )
    assert wrote is False
    assert not (tmp_path / "forecasts.parquet").exists()


def test_gate_disabled_always_publishes(tmp_path):
    # Enforcement OFF -> release_blocked is False even for an ineligible model.
    promotion = _promotion_assessment(_ineligible_metrics(), "hist_gbm")
    release_blocked = False and not promotion["public_release_eligible"]
    wrote = _publish_forecasts_unless_blocked(
        tmp_path, [{"beach_id": "b1", "risk_band": "FRESH"}], release_blocked=release_blocked
    )
    assert wrote is True
    assert (tmp_path / "forecasts.parquet").exists()


# --- verify_release_gate.py -------------------------------------------------


def _write_health(curated_dir, payload: dict) -> None:
    (curated_dir / "system_health.json").write_text(json.dumps(payload))


def test_resolve_eligibility_prefers_release_gate_block():
    eligible, blockers = vrg._resolve_eligibility(
        {"release_gate": {"public_release_eligible": False, "blockers": ["b1", "b2"]}}
    )
    assert eligible is False
    assert blockers == ["b1", "b2"]


def test_resolve_eligibility_falls_back_to_model_registry():
    eligible, blockers = vrg._resolve_eligibility(
        {"model_registry": {"public_release_eligible": True, "promotion_blockers": []}}
    )
    assert eligible is True
    assert blockers == []


def test_resolve_eligibility_fails_closed_without_verdict():
    eligible, blockers = vrg._resolve_eligibility({"something_else": 1})
    assert eligible is False
    assert blockers  # explains the fail-closed


def test_verify_script_exit_zero_when_eligible(tmp_path, capsys):
    _write_health(tmp_path, {"release_gate": {"public_release_eligible": True, "blockers": []}})
    rc = _run_main(tmp_path)
    assert rc == 0
    assert "RELEASE GATE PASSED" in capsys.readouterr().out


def test_verify_script_exit_one_and_prints_blockers_when_ineligible(tmp_path, capsys):
    _write_health(
        tmp_path,
        {"release_gate": {"public_release_eligible": False, "blockers": ["spatial county AUCPR below persistence"]}},
    )
    rc = _run_main(tmp_path)
    assert rc == 1
    err = capsys.readouterr().err
    assert "RELEASE GATE FAILED" in err
    assert "spatial county AUCPR below persistence" in err


def test_verify_script_fails_closed_on_missing_file(tmp_path, capsys):
    rc = _run_main(tmp_path)
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def _run_main(curated_dir) -> int:
    import sys

    argv = sys.argv
    sys.argv = ["verify_release_gate.py", "--curated", str(curated_dir)]
    try:
        return vrg.main()
    finally:
        sys.argv = argv
