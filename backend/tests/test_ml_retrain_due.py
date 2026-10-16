"""The XGB challenger retrains when new lab results land, at most once a Pacific day.

xgb-retrain.yml chains to the daily forecast's completion and dispatches a
run_ml=true forecast run when ``scripts/ml_retrain_due.py`` says the labels in
beach_day.parquet differ from the marker the last training wrote. The workflow
tests at the bottom pin the chain: workflow_run matches the forecast workflow by
``name:``, so a rename breaks it with no error anywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT.parent / ".github" / "workflows"
spec = importlib.util.spec_from_file_location("ml_retrain_due", ROOT / "scripts" / "ml_retrain_due.py")
due = importlib.util.module_from_spec(spec)
spec.loader.exec_module(due)

# 2026-10-15 09:30 PT and the previous Pacific day.
NOW = datetime(2026, 10, 15, 16, 30, tzinfo=UTC)
YESTERDAY_PT = datetime(2026, 10, 15, 5, 0, tzinfo=UTC)  # 2026-10-14 22:00 PT


def _beach_day(rows):
    return pd.DataFrame(rows, columns=["beach_id", "sample_date", "exceeds_stv"]).assign(
        sample_date=lambda d: pd.to_datetime(d["sample_date"])
    )


BASE = [("a", "2026-10-01", False), ("a", "2026-10-08", True), ("b", "2026-10-02", False)]


def _curated(tmp_path, rows=BASE):
    curated = tmp_path / "curated"
    curated.mkdir(exist_ok=True)
    _beach_day(rows).to_parquet(curated / "beach_day.parquet", index=False)
    return curated


def test_fingerprint_ignores_row_order():
    assert due.label_summary(_beach_day(BASE)) == due.label_summary(_beach_day(BASE[::-1]))


def test_a_corrected_label_and_a_late_old_result_both_change_the_fingerprint():
    base = due.label_summary(_beach_day(BASE))
    relabelled = due.label_summary(_beach_day([("a", "2026-10-01", True)] + BASE[1:]))
    late_old = due.label_summary(_beach_day(BASE + [("c", "2026-09-01", False)]))
    assert relabelled["fingerprint"] != base["fingerprint"]
    assert late_old["fingerprint"] != base["fingerprint"]
    # The late row is older than the newest date: a newest-date check would miss it.
    assert late_old["newest_sample_date"] == base["newest_sample_date"]


def test_rows_without_a_label_are_not_lab_results():
    unlabelled = _beach_day(BASE).astype({"exceeds_stv": "object"})
    unlabelled.loc[len(unlabelled)] = ["c", pd.Timestamp("2026-10-09"), None]
    assert due.label_summary(unlabelled) == due.label_summary(_beach_day(BASE))


def test_no_marker_is_due(tmp_path):
    assert due.retrain_due(_curated(tmp_path), now=NOW)["reason"] == "no_marker"


def test_unchanged_labels_are_not_due(tmp_path):
    curated = _curated(tmp_path)
    due.write_marker(curated, now=YESTERDAY_PT)
    result = due.retrain_due(curated, now=NOW)
    assert (result["due"], result["reason"], result["new_labels"]) == (False, "no_new_lab_results", 0)


def test_new_lab_results_are_due(tmp_path):
    curated = _curated(tmp_path)
    due.write_marker(curated, now=YESTERDAY_PT)
    _curated(tmp_path, BASE + [("b", "2026-10-09", True)])
    result = due.retrain_due(curated, now=NOW)
    assert (result["due"], result["reason"], result["new_labels"]) == (True, "new_lab_results", 1)


def test_at_most_one_retrain_per_pacific_day(tmp_path):
    """The ML run's own completion must not dispatch another ML run."""
    curated = _curated(tmp_path)
    due.write_marker(curated, now=datetime(2026, 10, 15, 15, 0, tzinfo=UTC))  # 08:00 PT today
    _curated(tmp_path, BASE + [("b", "2026-10-09", True)])
    result = due.retrain_due(curated, now=NOW)
    assert (result["due"], result["reason"]) == (False, "already_trained_today")


def test_the_day_is_pacific_not_utc(tmp_path):
    curated = _curated(tmp_path)
    # Same UTC date as NOW, previous Pacific date.
    due.write_marker(curated, now=YESTERDAY_PT)
    _curated(tmp_path, BASE + [("b", "2026-10-09", True)])
    assert due.retrain_due(curated, now=NOW)["due"] is True


def test_cli_writes_github_outputs(tmp_path):
    curated = _curated(tmp_path)
    out = tmp_path / "gh_output"
    script = ROOT / "scripts" / "ml_retrain_due.py"
    subprocess.run([sys.executable, str(script), "--curated", str(curated), "--github-output", str(out)], check=True)
    assert out.read_text().splitlines() == ["due=true", "reason=no_marker"]
    subprocess.run([sys.executable, str(script), "--curated", str(curated), "--write-marker"], check=True)
    marker = json.loads((curated / due.MARKER_NAME).read_text())
    assert marker["n_labels"] == 3 and marker["newest_sample_date"] == "2026-10-08"


def test_retrain_workflow_is_chained_to_the_forecast_by_its_exact_name():
    forecast = (WORKFLOWS / "daily-forecast.yml").read_text()
    forecast_name = re.search(r"^name:\s*(.+?)\s*$", forecast, re.M).group(1).strip("'\"")
    retrain = (WORKFLOWS / "xgb-retrain.yml").read_text()
    assert re.search(r"^\s*workflow_run:", retrain, re.M)
    listed = re.search(r"^\s*workflows:\s*\[([^\]]*)\]", retrain, re.M)
    assert forecast_name in [n.strip().strip("'\"") for n in listed.group(1).split(",")]
    assert "gh workflow run daily-forecast.yml" in retrain and "-f run_ml=true" in retrain
    assert "actions: write" in retrain


def test_the_ml_run_writes_the_marker_after_training_and_before_the_commit():
    forecast = (WORKFLOWS / "daily-forecast.yml").read_text()
    train = forecast.index("python -m app.ml.training")
    marker = forecast.index("scripts/ml_retrain_due.py --curated ../data/curated/ --write-marker")
    commit = forecast.index("git add data/curated/")
    assert train < marker < commit
