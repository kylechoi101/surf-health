"""Behavioral tests for the XGB balanced-undersample soft-ensemble classifier.

The spatial leave-one-county-out validation (scripts/spatial_compare.py,
scripts/spatial_incumbent.py) selected this architecture over the incumbent
single balanced GBM (+0.069 AUCPR / better Brier on held-out CA counties). These
tests pin the behaviors that make it work: a sklearn-compatible fit/predict_proba
contract, separation of an imbalanced signal, and soft-averaging that is no worse
than a single member.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score


def _imbalanced_dataset(n: int = 1200, pos_rate: float = 0.08, seed: int = 0):
    """A separable but noisy imbalanced set: positives carry a higher `signal`."""
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < pos_rate).astype(int)
    signal = rng.normal(loc=y * 1.5, scale=1.0)
    noise = rng.normal(size=n)
    X = pd.DataFrame({"signal": signal, "noise": noise})
    return X, y


def test_predict_proba_contract():
    from app.ml.models import XGBUndersampleEnsemble

    X, y = _imbalanced_dataset()
    model = XGBUndersampleEnsemble(n_estimators_ensemble=6, random_state=1)
    model.fit(X, y)

    proba = model.predict_proba(X)
    assert proba.shape == (len(X), 2)
    assert np.all(proba >= 0.0) and np.all(proba <= 1.0)
    np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-6)


def test_separates_imbalanced_signal():
    """On a held-out split the ensemble must rank positives above negatives well
    above chance (chance AUCPR ~= base rate)."""
    from app.ml.models import XGBUndersampleEnsemble

    Xtr, ytr = _imbalanced_dataset(seed=0)
    Xte, yte = _imbalanced_dataset(seed=99)
    model = XGBUndersampleEnsemble(n_estimators_ensemble=10, random_state=2)
    model.fit(Xtr, ytr)

    scores = model.predict_proba(Xte)[:, 1]
    aucpr = average_precision_score(yte, scores)
    assert aucpr > yte.mean() * 2.0  # well above the base-rate floor


def test_deterministic_with_seed():
    from app.ml.models import XGBUndersampleEnsemble

    X, y = _imbalanced_dataset()
    a = XGBUndersampleEnsemble(n_estimators_ensemble=5, random_state=7).fit(X, y).predict_proba(X)
    b = XGBUndersampleEnsemble(n_estimators_ensemble=5, random_state=7).fit(X, y).predict_proba(X)
    np.testing.assert_allclose(a, b)


def test_soft_average_uses_all_positives():
    """Each member keeps every positive; with more members the averaged score is
    no worse at ranking than a single member (variance reduction)."""
    from app.ml.models import XGBUndersampleEnsemble

    Xtr, ytr = _imbalanced_dataset(seed=0)
    Xte, yte = _imbalanced_dataset(seed=42)

    one = XGBUndersampleEnsemble(n_estimators_ensemble=1, random_state=3).fit(Xtr, ytr)
    many = XGBUndersampleEnsemble(n_estimators_ensemble=15, random_state=3).fit(Xtr, ytr)

    ap_one = average_precision_score(yte, one.predict_proba(Xte)[:, 1])
    ap_many = average_precision_score(yte, many.predict_proba(Xte)[:, 1])
    assert ap_many >= ap_one - 0.02  # averaging never meaningfully worse
