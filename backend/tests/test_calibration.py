import numpy as np
import pandas as pd

from app.ml.calibration import (
    HierarchicalProbabilityCalibrator,
    RISK_BAND_DESCRIPTIONS,
    confidence_capped_risk_band,
    risk_band,
)


def test_hierarchical_calibrator_partially_pools_county_and_site_effects():
    probabilities = np.array(
        [0.2, 0.25, 0.3, 0.35, 0.2, 0.25, 0.3, 0.35, 0.65, 0.7, 0.75, 0.8]
    )
    labels = np.array([1, 1, 1, 0, 0, 0, 0, 1, 0, 0, 1, 1])
    metadata = pd.DataFrame(
        {
            "county": ["warm"] * 4 + ["cool"] * 4 + ["warm"] * 4,
            "beach_id": ["site-a"] * 4 + ["site-b"] * 4 + ["site-c"] * 4,
        }
    )

    calibrator = HierarchicalProbabilityCalibrator(
        county_prior_strength=1.0,
        site_prior_strength=1.0,
        min_county_rows=4,
        min_site_rows=4,
    ).fit(probabilities, labels, metadata)

    scored = calibrator.transform(
        np.array([0.3, 0.3]),
        pd.DataFrame({"county": ["warm", "cool"], "beach_id": ["site-a", "site-b"]}),
    )

    assert scored[0] > scored[1]
    assert 0.0 < scored.min() < scored.max() < 1.0


def test_hierarchical_calibrator_returns_probability_intervals():
    probabilities = np.linspace(0.1, 0.9, 12)
    labels = np.array([0, 0, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1])
    metadata = pd.DataFrame(
        {
            "county": ["known"] * 8 + ["other"] * 4,
            "beach_id": ["known-site"] * 8 + ["other-site"] * 4,
        }
    )
    calibrator = HierarchicalProbabilityCalibrator(min_county_rows=4, min_site_rows=4).fit(
        probabilities, labels, metadata
    )

    prediction_metadata = pd.DataFrame(
        {"county": ["known", "unknown"], "beach_id": ["known-site", "unknown-site"]}
    )
    point = calibrator.transform(np.array([0.6, 0.6]), prediction_metadata)
    lower, upper = calibrator.predict_interval(np.array([0.6, 0.6]), prediction_metadata)

    assert lower.shape == upper.shape == point.shape
    assert np.all(lower <= point)
    assert np.all(point <= upper)
    assert (upper[1] - lower[1]) >= (upper[0] - lower[0])


def test_confidence_cap_downgrades_strong_band_when_very_stale_and_no_advisory():
    # High (0.45) and Very High (0.80) both cap to Moderate when the sample is
    # very stale / unknown and no advisory is active — the false-alarm lever.
    assert confidence_capped_risk_band(
        0.45, sample_recency_band="very_stale", advisory_active=False
    ) == "Moderate"
    assert confidence_capped_risk_band(
        0.80, sample_recency_band="unknown", advisory_active=False
    ) == "Moderate"


def test_confidence_cap_never_overrides_active_advisory():
    # An active advisory always wins; the cap must not suppress.
    assert confidence_capped_risk_band(
        0.80, sample_recency_band="very_stale", advisory_active=True
    ) == risk_band(0.80)


def test_confidence_cap_leaves_fresh_and_weak_bands_untouched():
    # Fresh/recent/stale samples are never capped (no added false negatives on
    # recent data), and Low/Moderate bands are unaffected regardless of recency.
    assert confidence_capped_risk_band(
        0.45, sample_recency_band="fresh", advisory_active=False
    ) == "High"
    assert confidence_capped_risk_band(
        0.45, sample_recency_band="stale", advisory_active=False
    ) == "High"
    assert confidence_capped_risk_band(
        0.10, sample_recency_band="very_stale", advisory_active=False
    ) == "Low"
    assert confidence_capped_risk_band(
        0.25, sample_recency_band="very_stale", advisory_active=False
    ) == "Moderate"


def test_risk_band_descriptions_are_model_estimates_not_official_safety_claims():
    copy = " ".join(RISK_BAND_DESCRIPTIONS.values()).lower()

    assert "model estimate" in copy or "model estimates" in copy
    assert "not an official advisory" in copy
    assert "swimming is not recommended" not in copy
    assert "unsafe" not in copy
