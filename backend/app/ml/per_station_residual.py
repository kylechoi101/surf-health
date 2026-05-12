"""Per-station residual GBM correction on top of the global classifier.

Diagnostic background: our data has a 1-to-1 mapping between beach_id and
station_code, so the HierarchicalProbabilityCalibrator's station-level intercept
duplicates its beach-level intercept. Calibration alone can only shift mean
exceedance rates per station; it can't capture station-specific *feature
response* shifts (e.g., a beach where rainfall has 3× the typical effect on
bacteria).

This module sits between the global hist-GBM and the calibrator. For every
station with enough labelled history, it fits a tiny shallow GBM on the
residual error `y_true - p_global`, then adds that prediction back to the
global probability at inference time. Stations without enough samples skip
correction and fall through to global + calibration only.

Design choices:
  * Shallow trees (max_depth=3) + few estimators (n_estimators=50) + small
    learning_rate (0.05) → cheap to train, ~100KB per station, resistant to
    overfitting on thin per-station data.
  * Floor: ≥30 labelled samples per station. Below that the residual GBM
    overfits.
  * Correction bounds: residual prediction clipped to [-0.3, 0.3] before
    being added to the global probability. Keeps a single station from
    driving any forecast to certainty.
  * Parallel training via joblib (n_jobs configurable, default 12 on M4 Pro).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor


MIN_ROWS_PER_STATION: int = 30
RESIDUAL_BOUND: float = 0.30  # max additive correction in either direction


@dataclass
class _StationRegressor:
    station_id: str
    model: HistGradientBoostingRegressor
    n_train_rows: int


def _fit_one_station(
    station_id: str,
    features: pd.DataFrame,
    residuals: np.ndarray,
) -> _StationRegressor | None:
    """Fit a shallow GBM on residuals for one station. Returns None if too thin."""
    if len(features) < MIN_ROWS_PER_STATION:
        return None
    # If all residuals are essentially zero, no signal to fit.
    if float(np.std(residuals)) < 1e-4:
        return None
    model = HistGradientBoostingRegressor(
        max_depth=3,
        max_iter=50,
        learning_rate=0.05,
        l2_regularization=1.0,
        min_samples_leaf=8,
        random_state=0,
    )
    model.fit(features, residuals)
    return _StationRegressor(
        station_id=station_id,
        model=model,
        n_train_rows=int(len(features)),
    )


class PerStationResidualEnsemble:
    """A trained collection of one shallow GBM per qualifying station.

    Usage:
        ens = PerStationResidualEnsemble().fit(p_global, features, labels, station_ids)
        p_corrected = ens.predict(p_global, features, station_ids)
    """

    def __init__(self, n_jobs: int = 12, min_rows: int = MIN_ROWS_PER_STATION) -> None:
        self.n_jobs = n_jobs
        self.min_rows = min_rows
        self.regressors_: dict[str, _StationRegressor] = {}
        self.feature_columns_: list[str] = []

    def fit(
        self,
        global_probabilities: np.ndarray,
        features: pd.DataFrame,
        labels: np.ndarray,
        station_ids: pd.Series,
    ) -> "PerStationResidualEnsemble":
        global_probabilities = np.asarray(global_probabilities, dtype=float)
        labels = np.asarray(labels, dtype=float)
        residuals = labels - global_probabilities
        station_ids = station_ids.astype(str).reset_index(drop=True)
        features = features.reset_index(drop=True)
        self.feature_columns_ = list(features.columns)

        # Group sample indices by station
        groups: dict[str, np.ndarray] = {}
        for idx, sid in enumerate(station_ids.to_numpy()):
            groups.setdefault(sid, []).append(idx)

        # Filter to stations meeting the row floor
        viable = {sid: np.asarray(rows, dtype=int)
                  for sid, rows in groups.items()
                  if len(rows) >= self.min_rows and sid not in ("", "nan", "None")}

        if not viable:
            return self

        # Parallel fit across stations. Each fit is cheap; the overhead is
        # task dispatch + serialization, hence backend="threading" rather than
        # the default "loky" — threads share memory and avoid pickling features.
        results = joblib.Parallel(n_jobs=self.n_jobs, backend="threading")(
            joblib.delayed(_fit_one_station)(
                sid,
                features.iloc[rows],
                residuals[rows],
            )
            for sid, rows in viable.items()
        )

        for fitted in results:
            if fitted is not None:
                self.regressors_[fitted.station_id] = fitted

        return self

    def predict(
        self,
        global_probabilities: np.ndarray,
        features: pd.DataFrame,
        station_ids: pd.Series,
    ) -> np.ndarray:
        """Return corrected probabilities. Stations without a fitted regressor
        return the global probability unchanged.
        """
        global_probabilities = np.asarray(global_probabilities, dtype=float).copy()
        station_ids = station_ids.astype(str).reset_index(drop=True).to_numpy()
        features = features.reset_index(drop=True)

        # Group by station for batched predict() calls
        groups: dict[str, list[int]] = {}
        for idx, sid in enumerate(station_ids):
            if sid in self.regressors_:
                groups.setdefault(sid, []).append(idx)

        for sid, rows_list in groups.items():
            rows = np.asarray(rows_list, dtype=int)
            regressor = self.regressors_[sid]
            x = features.iloc[rows]
            # Defensive column alignment — feature drift can rename columns
            x = x.reindex(columns=self.feature_columns_, fill_value=0.0)
            delta = regressor.model.predict(x)
            delta = np.clip(delta, -RESIDUAL_BOUND, RESIDUAL_BOUND)
            global_probabilities[rows] = np.clip(
                global_probabilities[rows] + delta, 0.001, 0.999
            )

        return global_probabilities

    def save(self, path) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path) -> "PerStationResidualEnsemble":
        return joblib.load(path)

    def coverage_summary(self, station_ids: pd.Series | None = None) -> dict:
        """Diagnostic stats for the model card / system_health."""
        n_stations_fit = len(self.regressors_)
        sample_counts = [r.n_train_rows for r in self.regressors_.values()]
        out: dict = {
            "n_stations_with_correction": n_stations_fit,
            "median_rows_per_station": int(np.median(sample_counts)) if sample_counts else 0,
            "min_rows_threshold": self.min_rows,
            "residual_bound": RESIDUAL_BOUND,
        }
        if station_ids is not None:
            total = station_ids.nunique()
            out["coverage_fraction"] = float(n_stations_fit / total) if total else 0.0
        return out
