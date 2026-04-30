from pathlib import Path


def test_daily_workflow_runs_stormwater_before_training():
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "daily-forecast.yml"
    text = workflow.read_text()

    stormwater_index = text.find("app.data.pipeline.stormwater")
    training_index = text.find("app.ml.training")

    assert stormwater_index != -1
    assert training_index != -1
    assert stormwater_index < training_index
