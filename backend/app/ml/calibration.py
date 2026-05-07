from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


_EPSILON = 1e-4


def _clip_probabilities(probabilities: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(probabilities, dtype=float), _EPSILON, 1.0 - _EPSILON)


def _logit(probabilities: np.ndarray) -> np.ndarray:
    clipped = _clip_probabilities(probabilities)
    return np.log(clipped / (1.0 - clipped))


def _inverse_logit(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    return 1.0 / (1.0 + np.exp(-values))


def _fit_logit_calibration(
    probabilities: np.ndarray,
    labels: np.ndarray,
) -> tuple[float, float]:
    if len(probabilities) == 0 or len(np.unique(labels)) < 2:
        return 0.0, 1.0
    model = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
    model.fit(_logit(probabilities).reshape(-1, 1), np.asarray(labels, dtype=int))
    return float(model.intercept_[0]), float(model.coef_[0][0])


@dataclass(frozen=True)
class _CountyCalibration:
    intercept: float
    slope: float
    rows: int


@dataclass(frozen=True)
class _SiteCalibration:
    intercept: float
    rows: int


class ProbabilityCalibrator:
    def __init__(self) -> None:
        self.model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")

    def fit(self, probabilities: np.ndarray, labels: np.ndarray) -> "ProbabilityCalibrator":
        self.model.fit(probabilities, labels)
        return self

    def transform(self, probabilities: np.ndarray) -> np.ndarray:
        return self.model.predict(probabilities)


class HierarchicalProbabilityCalibrator:
    """Empirical-Bayes partial-pooling calibration over model probabilities.

    The fitted shape follows a lightweight approximation of:
    logit(p_it) = a_county + b_county * logit(q_it) + u_site.
    County intercept/slope and site intercept estimates are shrunk toward the
    global calibration according to group sample size.
    """

    def __init__(
        self,
        *,
        county_prior_strength: float = 64.0,
        site_prior_strength: float = 24.0,
        station_prior_strength: float = 24.0,
        min_county_rows: int = 24,
        min_site_rows: int = 8,
        min_station_rows: int = 16,
    ) -> None:
        self.county_prior_strength = county_prior_strength
        self.site_prior_strength = site_prior_strength
        self.station_prior_strength = station_prior_strength
        self.min_county_rows = min_county_rows
        self.min_site_rows = min_site_rows
        self.min_station_rows = min_station_rows
        self.global_intercept_ = 0.0
        self.global_slope_ = 1.0
        self.county_calibrations_: dict[str, _CountyCalibration] = {}
        self.site_calibrations_: dict[str, _SiteCalibration] = {}
        self.station_calibrations_: dict[str, _SiteCalibration] = {}
        self.residual_variance_ = 0.05

    def fit(
        self,
        probabilities: np.ndarray,
        labels: np.ndarray,
        metadata: pd.DataFrame | None = None,
    ) -> "HierarchicalProbabilityCalibrator":
        probabilities = _clip_probabilities(probabilities)
        labels = np.asarray(labels, dtype=int)
        self.global_intercept_, self.global_slope_ = _fit_logit_calibration(probabilities, labels)
        if metadata is None or metadata.empty:
            return self

        metadata = metadata.reset_index(drop=True)
        county_series = metadata.get("county", pd.Series(index=metadata.index, dtype="object")).fillna("")
        for county, group_index in county_series.groupby(county_series).groups.items():
            rows = np.array(list(group_index), dtype=int)
            if not county or len(rows) < self.min_county_rows or len(np.unique(labels[rows])) < 2:
                continue
            intercept, slope = _fit_logit_calibration(probabilities[rows], labels[rows])
            weight = len(rows) / (len(rows) + self.county_prior_strength)
            self.county_calibrations_[str(county)] = _CountyCalibration(
                intercept=self.global_intercept_ * (1.0 - weight) + intercept * weight,
                slope=self.global_slope_ * (1.0 - weight) + slope * weight,
                rows=int(len(rows)),
            )

        county_logits = self._linear_predictor(probabilities, metadata)
        site_series = metadata.get("beach_id", pd.Series(index=metadata.index, dtype="object")).fillna("")
        for site, group_index in site_series.groupby(site_series).groups.items():
            rows = np.array(list(group_index), dtype=int)
            if not site or len(rows) < self.min_site_rows:
                continue
            observed_rate = (float(labels[rows].sum()) + 0.5) / (float(len(rows)) + 1.0)
            predicted_rate = float(_inverse_logit(county_logits[rows]).mean())
            raw_offset = float(_logit(np.array([observed_rate]))[0] - _logit(np.array([predicted_rate]))[0])
            weight = len(rows) / (len(rows) + self.site_prior_strength)
            self.site_calibrations_[str(site)] = _SiteCalibration(
                intercept=raw_offset * weight,
                rows=int(len(rows)),
            )

        # Optional: add a station-level intercept (partial pooling) when station_code
        # is present. This captures lab/agency-specific baseline shifts shared across
        # multiple beach_id aliases for the same monitoring station.
        if "station_code" in metadata.columns:
            station_series = metadata.get("station_code", pd.Series(index=metadata.index, dtype="object")).fillna("")
            for station, group_index in station_series.groupby(station_series).groups.items():
                rows = np.array(list(group_index), dtype=int)
                if not station or len(rows) < self.min_station_rows:
                    continue
                observed_rate = (float(labels[rows].sum()) + 0.5) / (float(len(rows)) + 1.0)
                predicted_rate = float(_inverse_logit(county_logits[rows]).mean())
                raw_offset = float(_logit(np.array([observed_rate]))[0] - _logit(np.array([predicted_rate]))[0])
                weight = len(rows) / (len(rows) + self.station_prior_strength)
                self.station_calibrations_[str(station)] = _SiteCalibration(
                    intercept=raw_offset * weight,
                    rows=int(len(rows)),
                )

        fitted_logits = self._linear_predictor(probabilities, metadata)
        fitted = _inverse_logit(fitted_logits)
        residuals = labels.astype(float) - fitted
        if len(residuals):
            self.residual_variance_ = max(0.01, float(np.var(residuals)))
        return self

    def _linear_predictor(
        self,
        probabilities: np.ndarray,
        metadata: pd.DataFrame | None = None,
    ) -> np.ndarray:
        logits = self.global_intercept_ + self.global_slope_ * _logit(probabilities)
        if metadata is None or metadata.empty:
            return logits

        metadata = metadata.reset_index(drop=True)
        county_series = metadata.get("county", pd.Series(index=metadata.index, dtype="object")).fillna("")
        for county, calibration in self.county_calibrations_.items():
            mask = county_series.eq(county).to_numpy()
            if mask.any():
                logits[mask] = calibration.intercept + calibration.slope * _logit(probabilities[mask])

        site_series = metadata.get("beach_id", pd.Series(index=metadata.index, dtype="object")).fillna("")
        for site, calibration in self.site_calibrations_.items():
            mask = site_series.eq(site).to_numpy()
            if mask.any():
                logits[mask] = logits[mask] + calibration.intercept
        if "station_code" in metadata.columns and self.station_calibrations_:
            station_series = metadata.get("station_code", pd.Series(index=metadata.index, dtype="object")).fillna("")
            for station, calibration in self.station_calibrations_.items():
                mask = station_series.eq(station).to_numpy()
                if mask.any():
                    logits[mask] = logits[mask] + calibration.intercept
        return logits

    def transform(
        self,
        probabilities: np.ndarray,
        metadata: pd.DataFrame | None = None,
    ) -> np.ndarray:
        return np.clip(_inverse_logit(self._linear_predictor(_clip_probabilities(probabilities), metadata)), 0.0, 1.0)

    def predict_interval(
        self,
        probabilities: np.ndarray,
        metadata: pd.DataFrame | None = None,
        credibility: float = 0.9,
    ) -> tuple[np.ndarray, np.ndarray]:
        z_score = 1.64 if credibility >= 0.9 else 1.0
        probabilities = _clip_probabilities(probabilities)
        logits = self._linear_predictor(probabilities, metadata)
        county_counts = np.zeros(len(probabilities), dtype=float)
        site_counts = np.zeros(len(probabilities), dtype=float)
        station_counts = np.zeros(len(probabilities), dtype=float)

        if metadata is not None and not metadata.empty:
            metadata = metadata.reset_index(drop=True)
            county_series = metadata.get("county", pd.Series(index=metadata.index, dtype="object")).fillna("")
            site_series = metadata.get("beach_id", pd.Series(index=metadata.index, dtype="object")).fillna("")
            station_series = metadata.get("station_code", pd.Series(index=metadata.index, dtype="object")).fillna("")
            for i, county in enumerate(county_series.astype(str)):
                county_counts[i] = self.county_calibrations_.get(county, _CountyCalibration(0.0, 1.0, 0)).rows
            for i, site in enumerate(site_series.astype(str)):
                site_counts[i] = self.site_calibrations_.get(site, _SiteCalibration(0.0, 0)).rows
            for i, station in enumerate(station_series.astype(str)):
                station_counts[i] = self.station_calibrations_.get(station, _SiteCalibration(0.0, 0)).rows

        half_width = z_score * np.sqrt(
            self.residual_variance_
            + 1.0 / (county_counts + 1.0)
            + 1.0 / (site_counts + 1.0)
            + 1.0 / (station_counts + 1.0)
        )
        lower = _inverse_logit(logits - half_width)
        upper = _inverse_logit(logits + half_width)
        return np.clip(lower, 0.0, 1.0), np.clip(upper, 0.0, 1.0)


# Thresholds calibrated for hist_gbm at ~11% base exceedance rate.
# "High" at 0.30 means the model estimates 3× the average beach's risk —
# not a certainty, but elevated enough to warrant caution.  "Very High"
# at 0.70 indicates genuinely extreme conditions (post-storm, CSO event,
# or active advisory near minimum-detection samples).
_LOW_THRESHOLD = 0.20
_HIGH_THRESHOLD = 0.30
_VERY_HIGH_THRESHOLD = 0.70

# Human-readable explanations shown in the app alongside each band.
RISK_BAND_DESCRIPTIONS: dict[str, str] = {
    "Low": "Water quality appears typical for this beach. Swim at your own discretion.",
    "Moderate": "Slightly elevated risk. Conditions may be less ideal; consider checking again before swimming.",
    "High": "Elevated risk — estimated exceedance probability is roughly 3× the average beach. Caution advised, especially for vulnerable groups.",
    "Very High": "High likelihood of unsafe bacteria levels. Swimming is not recommended until conditions improve. This may be due to an active advisory or model prediction.",
}


def risk_band(probability: float) -> str:
    if probability < _LOW_THRESHOLD:
        return "Low"
    if probability < _HIGH_THRESHOLD:
        return "Moderate"
    if probability < _VERY_HIGH_THRESHOLD:
        return "High"
    return "Very High"
