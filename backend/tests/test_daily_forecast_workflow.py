from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "daily-forecast.yml"


def test_daily_workflow_runs_stormwater_before_training():
    text = WORKFLOW.read_text()

    stormwater_index = text.find("app.data.pipeline.stormwater")
    training_index = text.find("app.ml.training")

    assert stormwater_index != -1
    assert training_index != -1
    assert stormwater_index < training_index


def test_scraper_gate_is_verified_after_the_commit_and_the_deploy():
    """The scraper gate must fail the job only once the day's work has shipped.

    After the commit/push, so the verdict and unresolved_advisories.parquet are
    auditable in git; and after the Render deploy, because that step is
    `if: success()` — failing earlier would commit a fresh forecast and then
    skip shipping it, leaving users on the stale snapshot. That is the exact
    outcome the 2026-08-05 severity split exists to prevent.
    """
    text = WORKFLOW.read_text()

    commit_index = text.find("chore: daily forecast refresh")
    deploy_index = text.find("Trigger Render deploy")
    verify_index = text.find("scripts/verify_scraper_gate.py")

    assert commit_index != -1
    assert deploy_index != -1
    assert verify_index != -1, "the daily workflow must verify the scraper gate"
    assert commit_index < verify_index
    assert deploy_index < verify_index
