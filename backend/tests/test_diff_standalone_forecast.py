import importlib.util
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "daily-forecast.yml"
_spec = importlib.util.spec_from_file_location("diff_standalone_forecast", ROOT / "backend/scripts/diff_standalone_forecast.py")
diff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diff)


def _frame(p=(0.1, 0.4), band=("Low", "High")):
    return pd.DataFrame(
        {
            "beach_id": ["a", "b"],
            "p_exceed": list(p),
            "risk_band": list(band),
            "advisory_floor_applied": [False, True],
            "persistence_floor_applied": [False, False],
            "p_exceed_ml": [0.2, 0.3],
            "forecast_generated_at": ["x", "y"],
        }
    )


def test_equal_inputs_match_and_ml_columns_are_ignored():
    shadow = _frame()
    shadow["p_exceed_ml"] = None
    shadow["forecast_generated_at"] = "z"
    result = diff.compare(_frame(), shadow)
    assert result["beaches_equal"] and result["n_diff"] == 0
    assert diff.verdict_line(result).startswith("SHADOW MATCH")


def test_differing_inputs_are_reported():
    result = diff.compare(_frame(), _frame(p=(0.1, 0.5), band=("Low", "Very High")))
    assert result["n_diff"] == 1
    assert abs(result["max_abs_dp"] - 0.1) < 1e-12
    assert result["rows"][0]["beach_id"] == "b"
    assert diff.verdict_line(result).startswith("SHADOW DIFF")


def test_tolerance_and_beach_set_mismatch():
    assert diff.compare(_frame(), _frame(p=(0.1 + 1e-12, 0.4)))["n_diff"] == 0
    result = diff.compare(_frame(), _frame().iloc[:1])
    assert not result["beaches_equal"] and result["missing_in_shadow"] == ["b"]


def test_cli_exits_zero_and_appends_log(tmp_path):
    real, shadow = tmp_path / "real", tmp_path / "shadow"
    real.mkdir()
    shadow.mkdir()
    _frame().to_parquet(real / "forecasts.parquet")
    _frame(p=(0.9, 0.4)).to_parquet(shadow / "forecasts.parquet")
    log = tmp_path / "log.jsonl"
    import sys

    argv = ["x", "--real", str(real), "--shadow", str(shadow), "--log", str(log), "--date", "2026-10-02"]
    old, sys.argv = sys.argv, argv
    try:
        assert diff.main() == 0
    finally:
        sys.argv = old
    record = json.loads(log.read_text())
    assert record["date"] == "2026-10-02" and record["n_diff"] == 1
    assert set(record) == {"date", "rows_real", "rows_shadow", "beaches_equal", "max_abs_dp", "n_diff"}


def test_missing_shadow_file_still_exits_zero(tmp_path):
    import sys

    old, sys.argv = sys.argv, ["x", "--real", str(tmp_path), "--shadow", str(tmp_path)]
    try:
        assert diff.main() == 0
    finally:
        sys.argv = old


def test_shadow_step_is_continue_on_error_and_runs_after_the_reapply_step():
    text = WORKFLOW.read_text()
    reapply = text.find("Re-apply the per-beach estimate after advisory expiry")
    start = text.find("- name: Shadow standalone serving (UPDATE_PLAN 3.4)")
    assert reapply != -1 and start != -1 and reapply < start
    end = text.find("\n      - name:", start + 1)
    step = text[start:end]
    assert re.search(r"^\s+continue-on-error: true", step, re.M)
    assert "--standalone" in step and "diff_standalone_forecast.py" in step
    assert "standalone_shadow_log.jsonl" in step
    assert "TZ=America/Los_Angeles date +%Y-%m-%d" in step and '--forecast-date "$FORECAST_DATE"' in step
    assert "Build API serving snapshot" in text[end:]
