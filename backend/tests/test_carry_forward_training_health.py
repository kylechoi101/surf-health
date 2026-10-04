"""A daily run without ML training must leave system_health.json whole."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("carry", SCRIPTS / "carry_forward_training_health.py")
carry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(carry)

PIPELINE_HEALTH = {
    "pipeline_freshness": "2026-10-05T19:00:00+00:00",
    "source_freshness": {"beaches": "2026-10-05T19:00:00+00:00"},
    "model_registry": {"production_model": "derived-persistence-v0", "candidate_models": [], "metrics": {}},
    "scraper_gate": {"passed": True},
    "serving_method": {"name": "logit-lookup-offset-v1"},
}
TRAINED_HEALTH = {
    "pipeline_freshness": "2026-10-04T20:16:43+00:00",
    "model_registry": {"production_model": "xgb-undersample-ensemble-curated-v0", "metrics": {"a": 1}},
    "serving_calibration": {"active": True},
    "served_metrics": {"generated_at": "old"},
    "release_gate": {"enforced": True, "public_release_eligible": False, "blockers": ["x"]},
}


def _setup(tmp_path, previous=TRAINED_HEALTH):
    curated = tmp_path / "curated"
    curated.mkdir(parents=True)
    (curated / "system_health.json").write_text(json.dumps(PIPELINE_HEALTH))
    prev = tmp_path / "prev.json"
    prev.write_text(json.dumps(previous))
    return curated, prev


def test_restores_the_registry_and_keeps_this_runs_keys(tmp_path):
    curated, prev = _setup(tmp_path)
    carry.carry_forward(curated, prev)
    health = json.loads((curated / "system_health.json").read_text())
    assert health["model_registry"] == TRAINED_HEALTH["model_registry"]
    assert health["serving_calibration"] == {"active": True}
    # this run's own stamps and steps are untouched
    for key in ("pipeline_freshness", "source_freshness", "scraper_gate", "serving_method"):
        assert health[key] == PIPELINE_HEALTH[key]
    # recomputed, not carried (no forecast_history here)
    assert health["served_metrics"] != TRAINED_HEALTH["served_metrics"]
    assert health["ml_training"]["ran"] is False
    assert health["ml_training"]["registry_carried_from"] == TRAINED_HEALTH["pipeline_freshness"]


def test_release_gate_passes_without_training(tmp_path):
    curated, prev = _setup(tmp_path)
    carry.carry_forward(curated, prev)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "verify_release_gate.py"), "--curated", str(curated)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_second_skipped_day_keeps_the_original_training_stamp(tmp_path):
    curated, prev = _setup(tmp_path)
    carry.carry_forward(curated, prev)
    day_one = json.loads((curated / "system_health.json").read_text())
    curated2, prev2 = _setup(tmp_path / "d2", previous=day_one)
    carry.carry_forward(curated2, prev2)
    health = json.loads((curated2 / "system_health.json").read_text())
    assert health["ml_training"]["registry_carried_from"] == TRAINED_HEALTH["pipeline_freshness"]
    assert health["model_registry"] == TRAINED_HEALTH["model_registry"]


def test_missing_previous_file_keeps_the_pipeline_health(tmp_path):
    curated, _ = _setup(tmp_path)
    carry.carry_forward(curated, tmp_path / "missing.json")
    health = json.loads((curated / "system_health.json").read_text())
    assert health["model_registry"] == PIPELINE_HEALTH["model_registry"]
    assert health["release_gate"]["public_release_eligible"] is True
