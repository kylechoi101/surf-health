"""Tests for scripts/verify_deploy.py — the served-vs-committed freshness gate.

The bug this guards against: fresh data is committed to main, the Render deploy
hook is POSTed, the POST succeeds, the workflow goes green — and the previous
image keeps serving because the build never shipped. Nothing detected that,
so the app's "last updated" silently fell a day behind.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_deploy.py"
_spec = importlib.util.spec_from_file_location("verify_deploy", _SCRIPT)
verify_deploy = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(verify_deploy)


_EXPECTED = datetime(2026, 7, 24, 19, 13, 11, tzinfo=timezone.utc)


def test_matching_snapshot_is_live():
    assert verify_deploy._is_live(_EXPECTED, _EXPECTED)


def test_newer_served_snapshot_is_live():
    # A concurrent deploy of a later commit also carries this run's data.
    assert verify_deploy._is_live(_EXPECTED + timedelta(minutes=5), _EXPECTED)


def test_previous_days_snapshot_is_not_live():
    # The 2026-07-25 incident: served snapshot a full day behind the commit.
    assert not verify_deploy._is_live(_EXPECTED - timedelta(days=1), _EXPECTED)


def test_unreachable_endpoint_is_not_live():
    assert not verify_deploy._is_live(None, _EXPECTED)


def test_small_clock_skew_is_tolerated():
    assert verify_deploy._is_live(_EXPECTED - timedelta(seconds=2), _EXPECTED)


def test_local_freshness_reads_committed_timestamp(tmp_path):
    (tmp_path / "system_health.json").write_text(
        json.dumps({"pipeline_freshness": "2026-07-24T19:13:11+00:00"})
    )
    assert verify_deploy._local_freshness(tmp_path) == _EXPECTED


@pytest.mark.parametrize("payload", [{}, {"pipeline_freshness": "unknown"}, {"pipeline_freshness": "nope"}])
def test_unverifiable_local_freshness_fails_closed(tmp_path, payload):
    (tmp_path / "system_health.json").write_text(json.dumps(payload))
    with pytest.raises(SystemExit):
        verify_deploy._local_freshness(tmp_path)


def test_missing_health_file_fails_closed(tmp_path):
    with pytest.raises(SystemExit):
        verify_deploy._local_freshness(tmp_path)


def test_polling_gives_up_and_fails(tmp_path, monkeypatch, capsys):
    (tmp_path / "system_health.json").write_text(
        json.dumps({"pipeline_freshness": _EXPECTED.isoformat()})
    )
    stale = _EXPECTED - timedelta(days=1)
    monkeypatch.setattr(verify_deploy, "_fetch_served", lambda *a, **k: (stale, "stale"))
    monkeypatch.setattr(verify_deploy.time, "sleep", lambda _s: None)

    exit_code = verify_deploy.main(
        ["--curated", str(tmp_path), "--attempts", "3", "--interval", "0"]
    )

    assert exit_code == 1
    assert "never went live" in capsys.readouterr().err


def test_polling_succeeds_once_the_new_image_is_live(tmp_path, monkeypatch):
    (tmp_path / "system_health.json").write_text(
        json.dumps({"pipeline_freshness": _EXPECTED.isoformat()})
    )
    responses = [(None, "HTTP 503"), (_EXPECTED - timedelta(days=1), "stale"), (_EXPECTED, "live")]
    monkeypatch.setattr(verify_deploy, "_fetch_served", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(verify_deploy.time, "sleep", lambda _s: None)

    assert verify_deploy.main(["--curated", str(tmp_path), "--attempts", "5", "--interval", "0"]) == 0


def test_daily_workflow_verifies_the_deploy_after_triggering_it():
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "daily-forecast.yml"
    text = workflow.read_text()

    trigger_index = text.find("Trigger Render deploy")
    verify_index = text.find("scripts/verify_deploy.py")

    assert trigger_index != -1
    assert verify_index != -1, "daily-forecast must verify the deploy actually shipped"
    assert trigger_index < verify_index


def test_deploy_workflow_verifies_served_freshness():
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-backend.yml"
    assert "verify_deploy.py" in workflow.read_text()
