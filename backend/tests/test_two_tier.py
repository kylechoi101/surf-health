import numpy as np
import pandas as pd

from app.ml.stale_evaluation import RECENCY_COLUMN
from app.ml.two_tier import (
    beach_baseline_margin,
    margins_for,
    staleness_augmented_frame,
    within_beach_auroc,
    within_beach_auroc_by_lag,
)


def test_beach_baseline_margin_orders_and_shrinks():
    # dirty beach (mostly positive) vs clean beach (mostly negative)
    labels = [1] * 9 + [0] + [0] * 9 + [1]
    beaches = ["dirty"] * 10 + ["clean"] * 10
    margins, global_margin = beach_baseline_margin(labels, beaches)
    assert margins["dirty"] > global_margin > margins["clean"]
    # a 1-sample beach is shrunk almost entirely to the global rate
    m2, g2 = beach_baseline_margin([1, 0, 1, 0, 1], ["a", "a", "a", "a", "rare"])
    assert abs(m2["rare"] - g2) < abs(margins["dirty"] - global_margin)


def test_margins_for_falls_back_to_global():
    margins, global_margin = beach_baseline_margin([1, 0, 1, 0], ["a", "a", "b", "b"])
    out = margins_for(["a", "unseen"], margins, global_margin)
    assert out[0] == margins["a"]
    assert out[1] == global_margin


def test_within_beach_auroc_perfect_vs_lookup():
    # two beaches, each with a good and a bad day; probability tracks the label
    labels = [0, 1, 0, 1]
    beaches = ["a", "a", "b", "b"]
    perfect = within_beach_auroc(labels, [0.1, 0.9, 0.2, 0.8], beaches, min_samples=2)[0]
    assert perfect == 1.0
    # a per-beach CONSTANT (lookup table) cannot tell the days apart -> 0.5
    lookup = within_beach_auroc(labels, [0.3, 0.3, 0.7, 0.7], beaches, min_samples=2)[0]
    assert abs(lookup - 0.5) < 1e-9


def test_within_beach_auroc_skips_single_class_beach():
    # beach 'c' is all-clean -> excluded; only 'a' (2 rows) counts
    auroc, n_beaches, n_rows = within_beach_auroc(
        [0, 1, 0, 0], [0.1, 0.9, 0.2, 0.3], ["a", "a", "c", "c"], min_samples=2
    )
    assert n_beaches == 1 and n_rows == 2 and auroc == 1.0


def test_staleness_augmented_frame_censors_and_doubles():
    features = pd.DataFrame(
        {
            "enterococcus_geomean_30d_lagged": [100.0, 5.0],
            "precip_mm_24h": [3.0, 0.0],  # covariate: must survive censoring
            RECENCY_COLUMN: [6.0, 8.0],
        }
    )
    aug, is_stale = staleness_augmented_frame(features, cutoff_days=14)
    assert len(aug) == 4 and is_stale.sum() == 2
    stale = aug[is_stale]
    # bacteria-history (anchor) feature zeroed; recency forced to the cutoff
    assert (stale["enterococcus_geomean_30d_lagged"] == 0.0).all()
    assert (stale[RECENCY_COLUMN] >= 14).all()
    # the covariate is untouched (it is what carries the stale regime)
    assert list(aug[~is_stale]["precip_mm_24h"]) == [3.0, 0.0]
    assert list(stale["precip_mm_24h"]) == [3.0, 0.0]


def test_offset_ensemble_fits_separates_and_falls_back():
    from app.ml.models import XGBUndersampleOffsetEnsemble

    rng = np.random.default_rng(0)
    n = 600
    beach = rng.choice(["dirty", "clean"], size=n)
    cov = rng.normal(size=n)
    y = (rng.random(n) < np.where(beach == "dirty", 0.6, 0.05)).astype(int)
    X = pd.DataFrame(
        {
            "precip_mm_24h": cov,
            "enterococcus_geomean_30d_lagged": rng.random(n) * 40,
            RECENCY_COLUMN: rng.integers(1, 20, n).astype(float),
        }
    )
    m = XGBUndersampleOffsetEnsemble(n_estimators_ensemble=3, n_estimators=60)
    m.fit(X, y, beach_ids=beach)
    p = m.predict_proba(X, beach_ids=beach)[:, 1]
    # the offset separates chronically-dirty from chronically-clean beaches
    assert p[beach == "dirty"].mean() > p[beach == "clean"].mean()
    # predict without beach_ids (global-margin fallback) must not crash
    pg = m.predict_proba(X)[:, 1]
    assert ((pg >= 0) & (pg <= 1)).all()


def test_within_beach_auroc_by_lag_strata():
    rng = np.random.default_rng(0)
    n = 400
    beaches = rng.choice(["a", "b", "c", "d"], size=n)
    lags = rng.choice([2, 6, 10, 20], size=n)
    labels = rng.integers(0, 2, size=n)
    probs = rng.random(n)
    out = within_beach_auroc_by_lag(labels, probs, beaches, lags, min_rows_per_bin=20)
    assert any(k.startswith("lag_") for k in out)
    for stratum in out.values():
        assert 0.0 <= stratum["within_beach_auroc"] <= 1.0
