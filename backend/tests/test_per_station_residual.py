"""Tests for PerStationResidualEnsemble — the per-station residual correction
layer that sits on top of the global classifier's probabilities."""
import numpy as np
import pandas as pd

from app.ml.per_station_residual import PerStationResidualEnsemble, MIN_ROWS_PER_STATION


def _station_frame(station_id: str, n: int, rng: np.random.Generator) -> pd.DataFrame:
    x = rng.uniform(0.0, 1.0, size=n)
    # label is driven by the feature only for this station; the global model
    # (a flat 0.5) is blind to it, so there is a clear residual to learn.
    y = (x > 0.5).astype(int)
    return pd.DataFrame({"x": x, "station": station_id, "y": y})


def test_residual_corrects_station_specific_feature_response():
    rng = np.random.default_rng(0)
    df = pd.concat(
        [_station_frame("A", 200, rng), _station_frame("B", 200, rng)], ignore_index=True
    )
    features = df[["x"]]
    labels = df["y"].to_numpy()
    stations = df["station"]
    p_global = np.full(len(df), 0.5)  # global model is uninformative

    ens = PerStationResidualEnsemble(n_jobs=2).fit(p_global, features, labels, stations)
    corrected = ens.predict(p_global, features, stations)

    # The correction must move probabilities toward the labels: lower Brier than
    # the flat global baseline.
    base_brier = np.mean((p_global - labels) ** 2)
    corr_brier = np.mean((corrected - labels) ** 2)
    assert corr_brier < base_brier - 0.05
    # High-x samples should be pushed above 0.5, low-x below.
    assert corrected[df["x"] > 0.8].mean() > 0.5
    assert corrected[df["x"] < 0.2].mean() < 0.5


def test_thin_stations_fall_through_to_global_unchanged():
    rng = np.random.default_rng(1)
    df = _station_frame("thin", MIN_ROWS_PER_STATION - 1, rng)
    features = df[["x"]]
    labels = df["y"].to_numpy()
    stations = df["station"]
    p_global = np.full(len(df), 0.42)

    ens = PerStationResidualEnsemble(n_jobs=2).fit(p_global, features, labels, stations)
    corrected = ens.predict(p_global, features, stations)

    assert ens.coverage_summary()["n_stations_with_correction"] == 0
    np.testing.assert_allclose(corrected, p_global)


def test_correction_is_bounded():
    # Even with an extreme residual signal, the additive correction is clipped so a
    # single station can't drive a forecast to certainty.
    rng = np.random.default_rng(2)
    df = _station_frame("A", 300, rng)
    features = df[["x"]]
    labels = df["y"].to_numpy()
    stations = df["station"]
    p_global = np.full(len(df), 0.5)

    ens = PerStationResidualEnsemble(n_jobs=2).fit(p_global, features, labels, stations)
    corrected = ens.predict(p_global, features, stations)
    assert corrected.min() >= 0.001
    assert corrected.max() <= 0.999
    # bounded to +/- RESIDUAL_BOUND (0.30) around the 0.5 global prob
    assert corrected.min() >= 0.5 - 0.30 - 1e-9
    assert corrected.max() <= 0.5 + 0.30 + 1e-9
