from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


# Canonical clip for ANY probability->log-odds transform in the ML stack.
#
# This is the single definition on purpose. evaluation._calibration_slope used
# 1e-6 while the transform actually applied to served probabilities used 1e-4,
# so the reported slope — a PUBLICATION-BLOCKING gate metric at < 0.4 — was fit
# on a more extreme log-odds range than the pipeline ever produces, biasing it
# low in proportion to how many predictions saturate. Measured on the shipped
# leave-one-out holdouts: no candidate crosses the 0.4 gate either way (the
# winner moves 1.1467 -> 1.1523), but the saturated persistence baselines move
# ~50% (0.1039 -> 0.1559), which is exactly the regime where a silent
# disagreement between "the number we report" and "the number we apply" hides.
LOGIT_EPSILON = 1e-4
_EPSILON = LOGIT_EPSILON  # retained for existing internal references


def _clip_probabilities(probabilities: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(probabilities, dtype=float), LOGIT_EPSILON, 1.0 - LOGIT_EPSILON)


def logit(probabilities: np.ndarray) -> np.ndarray:
    """Log-odds of ``probabilities``, clipped to LOGIT_EPSILON at both rails."""
    clipped = _clip_probabilities(probabilities)
    return np.log(clipped / (1.0 - clipped))


_logit = logit


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


# --------------------------------------------------------------------------
# Public band cutpoints (Step 10, 2026-08-07) — see BAND_EVIDENCE below
# --------------------------------------------------------------------------
#
# THESE ARE RELATIVE RISK TIERS, NOT ABSOLUTE PROBABILITY LABELS. The top band
# realizes ~0.36-0.56, which is not a high *probability*; it is ~5-8x the
# ~0.069 base rate of the population the model serves. Every surface that
# renders a band MUST carry that framing — `band_definitions()` exists so no
# consumer has to restate it from memory. See `docs/STEP10_BANDS_2026-08-07.md`.
#
# The previous values (0.20 / 0.30 / 0.70) were set for hist_gbm at a ~11%
# assumed base rate and were never validated against outcomes. Measured on the
# 14,414-pair serving-calibration window they FAILED end-state property E2:
# Moderate realized 0.191 [0.124, 0.263] and High 0.241 [0.172, 0.314] — two
# bands the product renders differently, statistically indistinguishable.
#
#   Low/Moderate  0.20 -> 0.10  DERIVED. The transition in realized rate sits at
#       precal ~0.09-0.10 in the calibration-free decile scan (deciles 0-7 run
#       0.016-0.069, decile 8 [0.093, 0.159] jumps to 0.108) and the split is
#       clean at 0.10 in served-probability space in every one of the five
#       months in the window.
#   Moderate/High 0.30 -> 0.20  DERIVED, and required: moving only the Low cut
#       leaves Moderate [0.096, 0.186] and High [0.174, 0.312] still overlapping.
#       Supported in all five months (n >= 57/month above 0.20).
#   High/Very High     0.70     HELD — **PROVISIONAL, NOT DERIVED**. 95.1% of the
#       p >= 0.45 evidence and 96.6% of the p >= 0.70 evidence predates both the
#       two-tier router and the 2026-08-06 pin removal, so there is no honest way
#       to move it today. The plan's proposed 0.45 does not survive a beach-level
#       cluster bootstrap either (High [0.152, 0.282] vs Very High [0.227, 0.477]
#       overlap). It becomes derivable once Step 9's clean regime window matures
#       — projected 2026-10-06, ~60 days after this cutpoint change opens the new
#       serving regime.
#
# COUPLINGS — these constants are not only band edges:
#   `_LOW_THRESHOLD`  is also the positive-persistence floor and the non-finite
#       serving fallback. `_HIGH_THRESHOLD` is also the active-advisory floor.
#   Both safety properties are stated in BAND terms ("a beach whose last sample
#       exceeded is never displayed Low"; "a posted beach is never displayed Low
#       or Moderate"), and `risk_band` is LEFT-CLOSED (`p < cut`), so a row
#       floored to exactly the cut lands in the band ABOVE it. The guarantees
#       therefore hold for ANY value of these constants and move with them
#       automatically. `tests/test_risk_bands.py` pins that as a property.
_LOW_THRESHOLD = 0.10
_HIGH_THRESHOLD = 0.20
_VERY_HIGH_THRESHOLD = 0.70

# The top cutpoint is held rather than derived; consumers surface this so the
# distinction between "measured" and "inherited" is visible in the product.
_VERY_HIGH_IS_PROVISIONAL = True
VERY_HIGH_DERIVABLE_FROM = "2026-10-06"

# Realized outcome rates per band, MEASURED — not asserted. Frozen snapshot of
# the derivation in `docs/STEP10_BANDS_2026-08-07.md`; regenerate it there rather
# than editing numbers here. Deliberately static and dated: after the cutpoint
# change opens a new serving regime the live window holds ~0 rows for ~60 days,
# and a "live" figure computed off that would be noise wearing a measurement's
# name. Intervals are 95% bootstrap with the BEACH as the resampling unit (the
# same beach contributes up to ~100 correlated rows, so naive Wilson overstates
# precision by 2-3x).
BAND_EVIDENCE: dict[str, object] = {
    "measured_at": "2026-08-07",
    "source": "serving-calibration fit window (forecast_history x lab outcomes)",
    "window_days": 120,
    "window_start": "2026-04-23",
    "window_end": "2026-08-05",
    "n_pairs": 14414,
    "n_beaches": 544,
    "base_rate": 0.0689,
    "ci_method": "cluster bootstrap over beach_id, 4000 resamples",
    "bands": {
        "Low": {"n": 11233, "realized": 0.0364, "ci": [0.0279, 0.0456], "lift": 0.53},
        "Moderate": {"n": 1346, "realized": 0.1100, "ci": [0.0754, 0.1505], "lift": 1.60},
        "High": {"n": 1748, "realized": 0.2214, "ci": [0.1623, 0.2834], "lift": 3.21},
        "Very High": {"n": 87, "realized": 0.5632, "ci": [0.3387, 0.7476], "lift": 8.17},
    },
    "caveats": [
        "Scored on the ~1 day in 7 that carries a lab result; the other ~6 are "
        "unverifiable in principle.",
        "The Very High row is 87 pairs, 96.6% of them April-May 2026 — before the "
        "two-tier router and before the 2026-08-06 persistence-pin removal. Its "
        "cutpoint is held, not derived.",
        "Bands were assigned from the SERVED risk_band column, so the 7 rows whose "
        "band came from the confidence cap or the advisory floor are graded "
        "against the band the user actually saw.",
    ],
}

# Human-readable explanations shown in the app alongside each band.
#
# Rewritten 2026-08-07 (Step 10). The old copy read the bands as absolute
# probabilities ("a high exceedance probability", "roughly 3x the average
# beach" — a multiple that was asserted from the cutpoint, never measured).
# A band that realizes ~0.36-0.56 is not "high probability"; most of the time
# nothing is wrong. Every string below now names the RELATIVE tier and the
# measured multiple, so the label and the number cannot disagree.
RISK_BAND_DESCRIPTIONS: dict[str, str] = {
    "Low": (
        "Typical for this beach. In testing, about 4 in 100 days like this came "
        "back over the limit — roughly half the average day. This is a model "
        "estimate, not an official advisory or lab result."
    ),
    "Moderate": (
        "Somewhat riskier than an average day here — about 11 in 100 such days "
        "came back over the limit in testing, roughly 1.6x the average day. Most "
        "of the time the water still tests clean. This is a model estimate, not "
        "an official advisory or lab result."
    ),
    "High": (
        "Among the riskiest days this model flags — about 22 in 100 such days "
        "came back over the limit in testing, roughly 3x the average day. That "
        "still means most such days test clean; it is a relative ranking, not a "
        "determination about water safety. This is a model estimate, not an "
        "official advisory or lab result."
    ),
    "Very High": (
        "The model's top tier — about 56 in 100 such days came back over the "
        "limit in testing, roughly 8x the average day. It is the strongest signal "
        "the model gives, not a certainty. This cutpoint is provisional and is "
        "being re-measured. This is a model estimate, not an official advisory or "
        "lab result."
    ),
    "Advisory": (
        "Official county health advisory is currently posted for this beach. This "
        "is not a model prediction — the county has determined entering the water "
        "poses a health risk. See the county source for full details."
    ),
}

# One-line relative framing per band, for surfaces too small for the full copy
# above (map pins, list chips). Kept separate so a UI cannot accidentally render
# a bare adjective with no reference point.
RISK_BAND_RELATIVE_SUMMARY: dict[str, str] = {
    "Low": "about half the average day's risk",
    "Moderate": "about 1.6x the average day's risk",
    "High": "about 3x the average day's risk",
    "Very High": "about 8x the average day's risk",
    "Advisory": "official county posting — not a model estimate",
}

BAND_SEMANTICS = "relative_risk_tier"
BAND_SEMANTICS_NOTE = (
    "Bands are RELATIVE risk tiers, not absolute probabilities. They rank a "
    "beach-day against the ~6.9% base rate of the served population. Even the "
    "top band realized ~0.56 in testing, i.e. most such days still test clean."
)


def band_definitions() -> dict[str, object]:
    """Machine-readable band contract: cutpoints, semantics, and evidence.

    The single source consumers should read rather than hardcoding cutpoints or
    restating what a band means. Published three ways — into
    ``system_health.json`` by the training run, at ``/system/health`` by the API,
    and into the web static bake — all from this one function, so the numbers a
    UI renders cannot drift from the numbers ``risk_band`` actually applies.

    ``convention`` is load-bearing: the cut is LEFT-CLOSED (``p < cut``), which
    is what makes the persistence and advisory floors land one band above their
    own constant. A consumer that re-bands with a right-closed rule misassigns
    every row sitting exactly on a cutpoint — measured at 948 of 14,414 on the
    shipped history, because the serving isotonic's step plateaus land exactly
    there.
    """
    evidence_bands = BAND_EVIDENCE["bands"]
    assert isinstance(evidence_bands, dict)
    ranges: dict[str, list[float | None]] = {
        "Low": [0.0, _LOW_THRESHOLD],
        "Moderate": [_LOW_THRESHOLD, _HIGH_THRESHOLD],
        "High": [_HIGH_THRESHOLD, _VERY_HIGH_THRESHOLD],
        "Very High": [_VERY_HIGH_THRESHOLD, 1.0],
    }
    return {
        "semantics": BAND_SEMANTICS,
        "semantics_note": BAND_SEMANTICS_NOTE,
        "convention": "left_closed",  # band is `p < cut`
        "cutpoints": {
            "low_moderate": _LOW_THRESHOLD,
            "moderate_high": _HIGH_THRESHOLD,
            "high_very_high": _VERY_HIGH_THRESHOLD,
        },
        "base_rate": BAND_EVIDENCE["base_rate"],
        "evidence": {
            key: BAND_EVIDENCE[key]
            for key in (
                "measured_at",
                "source",
                "window_days",
                "window_start",
                "window_end",
                "n_pairs",
                "n_beaches",
                "ci_method",
                "caveats",
            )
        },
        "bands": [
            {
                "label": label,
                "p_range": ranges[label],
                "description": RISK_BAND_DESCRIPTIONS[label],
                "relative_summary": RISK_BAND_RELATIVE_SUMMARY[label],
                "derived": not (label == "Very High" and _VERY_HIGH_IS_PROVISIONAL),
                "provisional": label == "Very High" and _VERY_HIGH_IS_PROVISIONAL,
                "provisional_until": (
                    VERY_HIGH_DERIVABLE_FROM
                    if label == "Very High" and _VERY_HIGH_IS_PROVISIONAL
                    else None
                ),
                **{
                    key: evidence_bands[label][key]  # type: ignore[index]
                    for key in ("n", "realized", "ci", "lift")
                },
            }
            for label in ("Low", "Moderate", "High", "Very High")
        ],
    }


def risk_band(probability: float) -> str:
    if probability < _LOW_THRESHOLD:
        return "Low"
    if probability < _HIGH_THRESHOLD:
        return "Moderate"
    if probability < _VERY_HIGH_THRESHOLD:
        return "High"
    return "Very High"


def advisory_floored_probability(probability: float, advisory_active: bool) -> tuple[float, bool]:
    """Lift ``p_exceed`` to the High cutpoint while an official posting is active.

    This is the safety guarantee that lets ``risk_band`` stay the MODEL's band on a
    posted beach instead of being replaced by a synthetic "Advisory" band: floored
    at ``_HIGH_THRESHOLD`` a posted beach can never display Low or Moderate, so the
    badge and the band can never contradict each other.

    It exists because the pipeline's own floor (``advisory_active_recent_for_floor``,
    baked into the training feature frame) and the serve-time advisory flag (read
    from ``advisories.parquet``) are DIFFERENT sources and can disagree — a posting
    filed after the feature frame was built is absent from the feature. Measured
    2026-07-30 on the shipped bake: of 18 posted beaches with a forecast the
    feature-driven floor fired on 16, and the 2 it missed (Gazos Creek Access
    p=0.056, Keller Beach p=0.118) would have rendered "Low" under an active
    advisory. Driving the floor from the same flag that raises the badge closes
    that gap by construction.

    Returns ``(probability, floor_applied)``.
    """
    if not advisory_active:
        return probability, False
    if probability >= _HIGH_THRESHOLD:
        return probability, False
    return _HIGH_THRESHOLD, True


# Sample-recency bands (mirrors app.schemas.domain.sample_recency_band) that the
# confidence-aware display gate treats as "too stale to fire a strong warning"
# on a *model-only* prediction. Kept here so calibration owns the band policy.
_LOW_CONFIDENCE_RECENCY_BANDS: frozenset[str] = frozenset({"very_stale", "unknown"})


def confidence_capped_risk_band(
    probability: float,
    *,
    sample_recency_band: str | None,
    advisory_active: bool,
) -> str:
    """Display band with a conservative false-alarm gate, NOT a cutpoint change.

    FALSE-ALARM LEVER (does NOT touch the four public cutpoints, which the web +
    mobile UIs publish and depend on). The model raises ~12 false positives per
    false negative vs official advisories; the worst offenders are strong (High /
    Very High) bands fired off a stale model-only signal with no posting to back
    them up. When the underlying sample is *very stale* (>60 days old) or its age
    is unknown AND there is no active official advisory, the model has no recent
    evidence to justify a strong warning, so we cap the *displayed* band at
    Moderate. The numeric ``p_exceed`` is left untouched (honest), and:

      - An active advisory ALWAYS wins — the cap never suppresses a posted
        advisory (those route to the "Advisory" band upstream regardless).
      - Fresh / recent / stale (<= 60 days) samples are never capped, so this
        cannot raise the false-negative rate on recent data — exactly where a
        true lab exceedance would still be reflected.

    Returns the standard band for every non-low-confidence case.
    """
    band = risk_band(probability)
    if advisory_active:
        return band
    if band in ("High", "Very High") and (sample_recency_band in _LOW_CONFIDENCE_RECENCY_BANDS):
        return "Moderate"
    return band
