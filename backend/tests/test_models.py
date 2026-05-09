import pandas as pd

from app.ml.models import make_baselines


def test_hist_gradient_boosting_baselines_are_seeded_for_reproducible_gates():
    features = pd.DataFrame({"feature": [0.0, 1.0, 2.0]})

    baselines = make_baselines(features)

    assert baselines.tree_classifier.random_state == 42
    assert baselines.tree_regressor.random_state == 42
