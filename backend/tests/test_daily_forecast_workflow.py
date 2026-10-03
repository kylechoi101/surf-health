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


def test_lookup_estimate_is_reapplied_after_advisory_expiry_and_before_the_snapshot():
    """The served advisory floor must reflect advisories AFTER G.2 demotes zombies.

    On 2026-09-22 the only lookup step ran before G.2, flooring 81 beaches to High
    of which only 18 were still posted once G.2 ran. The last lookup invocation
    must sit after G.2 and before the serving snapshot and the commit.
    """
    text = WORKFLOW.read_text()

    expire_index = text.find("scripts/auto_expire_advisories.py")
    last_lookup_index = text.rfind("app.ml.lookup_serving")
    snapshot_index = text.find("app.data.pipeline.serving_snapshot")
    commit_index = text.find("chore: daily forecast refresh")

    assert expire_index != -1 and last_lookup_index != -1
    assert snapshot_index != -1 and commit_index != -1
    assert expire_index < last_lookup_index < snapshot_index < commit_index


def test_web_deploy_is_dispatched_after_the_commit_and_cannot_block_the_render_deploy():
    """The web bake must follow the data commit, not race it on its own cron.

    After the commit (the bake reads data/curated/ from main, so dispatching
    earlier would bake yesterday's data) and before the Render deploy, which is
    `if: success()` -- so the dispatch must be continue-on-error, or a failed
    call would leave the API on the stale snapshot.
    """
    text = WORKFLOW.read_text()

    commit_index = text.find("chore: daily forecast refresh")
    dispatch_index = text.find("repos/kylechoi101/shorelife-web/dispatches")
    render_index = text.find("Trigger Render deploy")

    assert dispatch_index != -1, "the daily workflow must dispatch the web deploy"
    assert commit_index < dispatch_index < render_index
    step = text[text.rfind("- name:", 0, dispatch_index):dispatch_index]
    assert "continue-on-error: true" in step
    # ...and it cannot hang into the job budget either.
    assert "timeout-minutes:" in step
    assert "--max-time" in text[dispatch_index - 600:dispatch_index]
    assert "backend-data-published" in text[dispatch_index - 2000:dispatch_index]
    # The token reaches the shell through env, never interpolated into the script.
    assert "${{ secrets.WEB_DEPLOY_DISPATCH_TOKEN }}" in step
    assert "secrets.WEB_DEPLOY_DISPATCH_TOKEN" not in text[text.find("run: |", text.rfind("- name:", 0, dispatch_index)):dispatch_index]


def test_advisory_step_has_github_models_token_and_permission():
    """Humboldt/Sonoma/SLO LLM extraction needs GITHUB_TOKEN and `models: read`."""
    text = WORKFLOW.read_text()

    refresh_index = text.find("  refresh:")
    permissions_index = text.find("    permissions:", refresh_index)
    steps_index = text.find("    steps:", refresh_index)
    assert refresh_index != -1 and permissions_index < steps_index
    permissions_block = text[permissions_index:steps_index]
    assert "contents: write" in permissions_block
    assert "models: read" in permissions_block

    step_index = text.find("- name: Fetch county-direct advisories")
    run_index = text.find("scripts/fetch_county_advisories.py", step_index)
    assert step_index != -1 and run_index != -1
    step_block = text[step_index:run_index]
    assert "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in step_block
