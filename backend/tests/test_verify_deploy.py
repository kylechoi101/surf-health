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


# --- re-triggering a stalled deploy (2026-09-02) --------------------------
#
# That day the pipeline succeeded, the forecast was committed and pushed, and
# the Render build never shipped: all 40 polls saw the previous day's snapshot.
# Detection alone left the fresh forecast unpublished until the NEXT day's cron
# POSTed the hook again, which is long enough for /system/health to cross its
# 36 h fail-closed limit.


def _stalled(tmp_path, monkeypatch, *, served=None):
    """Wire up a run where the served snapshot never advances."""
    (tmp_path / "system_health.json").write_text(
        json.dumps({"pipeline_freshness": _EXPECTED.isoformat()})
    )
    stale = served if served is not None else _EXPECTED - timedelta(days=1)
    monkeypatch.setattr(verify_deploy, "_fetch_served", lambda *a, **k: (stale, "stale"))
    monkeypatch.setattr(verify_deploy.time, "sleep", lambda _s: None)
    calls: list[str] = []
    monkeypatch.setattr(
        verify_deploy,
        "_retrigger_deploy",
        lambda url, _timeout: (calls.append(url), (True, "HTTP 200"))[1],
    )
    return calls


def test_stalled_deploy_is_retriggered_up_to_the_cap(tmp_path, monkeypatch):
    calls = _stalled(tmp_path, monkeypatch)
    monkeypatch.setenv("RENDER_DEPLOY_HOOK", "https://hook.example/deploy?key=s3cret")

    exit_code = verify_deploy.main(
        [
            "--curated",
            str(tmp_path),
            "--attempts",
            "12",
            "--interval",
            "0",
            "--retrigger-after",
            "3",
            "--max-retriggers",
            "2",
        ]
    )

    assert exit_code == 1
    assert calls == ["https://hook.example/deploy?key=s3cret"] * 2


def test_retrigger_waits_for_the_stall_window(tmp_path, monkeypatch):
    # A merely slow build must not be re-triggered: fewer polls than the
    # window means the hook is never re-POSTed at all.
    calls = _stalled(tmp_path, monkeypatch)
    monkeypatch.setenv("RENDER_DEPLOY_HOOK", "https://hook.example/deploy")

    verify_deploy.main(
        ["--curated", str(tmp_path), "--attempts", "3", "--interval", "0", "--retrigger-after", "10"]
    )

    assert calls == []


def test_no_retrigger_without_the_hook_in_the_environment(tmp_path, monkeypatch):
    calls = _stalled(tmp_path, monkeypatch)
    monkeypatch.delenv("RENDER_DEPLOY_HOOK", raising=False)

    exit_code = verify_deploy.main(
        ["--curated", str(tmp_path), "--attempts", "6", "--interval", "0", "--retrigger-after", "2"]
    )

    assert exit_code == 1
    assert calls == []


def test_max_retriggers_zero_restores_detect_and_fail(tmp_path, monkeypatch):
    calls = _stalled(tmp_path, monkeypatch)
    monkeypatch.setenv("RENDER_DEPLOY_HOOK", "https://hook.example/deploy")

    verify_deploy.main(
        [
            "--curated",
            str(tmp_path),
            "--attempts",
            "6",
            "--interval",
            "0",
            "--retrigger-after",
            "2",
            "--max-retriggers",
            "0",
        ]
    )

    assert calls == []


def test_retriggered_build_that_ships_verifies_green(tmp_path, monkeypatch):
    (tmp_path / "system_health.json").write_text(
        json.dumps({"pipeline_freshness": _EXPECTED.isoformat()})
    )
    monkeypatch.setenv("RENDER_DEPLOY_HOOK", "https://hook.example/deploy")
    monkeypatch.setattr(verify_deploy.time, "sleep", lambda _s: None)

    state = {"live": False}
    monkeypatch.setattr(
        verify_deploy,
        "_fetch_served",
        lambda *a, **k: (_EXPECTED, "live") if state["live"] else (_EXPECTED - timedelta(days=1), "stale"),
    )

    def _retrigger(_url, _timeout):
        state["live"] = True
        return True, "HTTP 200"

    monkeypatch.setattr(verify_deploy, "_retrigger_deploy", _retrigger)

    exit_code = verify_deploy.main(
        ["--curated", str(tmp_path), "--attempts", "8", "--interval", "0", "--retrigger-after", "2"]
    )

    assert exit_code == 0


def test_failure_message_names_the_spent_retriggers(tmp_path, monkeypatch, capsys):
    _stalled(tmp_path, monkeypatch)
    monkeypatch.setenv("RENDER_DEPLOY_HOOK", "https://hook.example/deploy")

    verify_deploy.main(
        ["--curated", str(tmp_path), "--attempts", "9", "--interval", "0", "--retrigger-after", "3"]
    )

    err = capsys.readouterr().err
    assert "re-POSTed 2x" in err
    assert "failing repeatably" in err


def test_the_hook_url_is_never_printed(tmp_path, monkeypatch, capsys):
    """The hook URL is a credential: holding it is authorisation to deploy."""
    secret = "https://api.render.com/deploy/srv-abc?key=s3cr3t"
    (tmp_path / "system_health.json").write_text(
        json.dumps({"pipeline_freshness": _EXPECTED.isoformat()})
    )
    monkeypatch.setenv("RENDER_DEPLOY_HOOK", secret)
    monkeypatch.setattr(verify_deploy.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        verify_deploy, "_fetch_served", lambda *a, **k: (_EXPECTED - timedelta(days=1), "stale")
    )
    # A urllib failure whose message embeds the URL — the realistic leak path.
    monkeypatch.setattr(
        verify_deploy.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError(f"cannot reach {secret}")),
    )

    verify_deploy.main(
        ["--curated", str(tmp_path), "--attempts", "4", "--interval", "0", "--retrigger-after", "2"]
    )

    captured = capsys.readouterr()
    assert "s3cr3t" not in captured.out + captured.err
    assert "<deploy-hook>" in captured.out


def test_redact_replaces_every_occurrence():
    assert verify_deploy._redact("a X b X", "X") == "a <deploy-hook> b <deploy-hook>"
    assert verify_deploy._redact("nothing to hide", "") == "nothing to hide"


def test_polling_budget_leaves_room_for_a_retriggered_build():
    """The last re-trigger must have time to land before the budget expires.

    A healthy Render build shipped in ~2 min (measured on the 2026-09-01 run),
    so the polls remaining after the final re-trigger have to exceed that.
    """
    interval = 30.0
    last_retrigger_at = verify_deploy._DEFAULT_RETRIGGER_AFTER * verify_deploy._DEFAULT_MAX_RETRIGGERS
    remaining_min = (verify_deploy._DEFAULT_ATTEMPTS - last_retrigger_at) * interval / 60
    assert remaining_min >= 10


def test_daily_workflow_passes_the_deploy_hook_to_the_verifier():
    """Without the env var wired in, the re-trigger path is dead in production."""
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "daily-forecast.yml"
    text = workflow.read_text()

    verify_step = text[text.find("Verify the fresh data actually went live") :]
    verify_step = verify_step[: verify_step.find("verify_deploy.py")]
    assert "RENDER_DEPLOY_HOOK" in verify_step


def test_deploy_workflow_passes_the_deploy_hook_to_the_verifier():
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-backend.yml"
    text = workflow.read_text()

    verify_step = text[text.find("Wait for Render deploy to become healthy") :]
    verify_step = verify_step[: verify_step.find("verify_deploy.py")]
    assert "RENDER_DEPLOY_HOOK" in verify_step


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
