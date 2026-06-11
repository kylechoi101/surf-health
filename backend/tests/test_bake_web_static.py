"""Guard the vendored risk-band logic in ``scripts/bake_web_static.py``.

``bake_web_static.py`` runs in the *web* repo's CI with no surf_health backend
deps installed, so it intentionally VENDORS (re-declares) the risk-band
thresholds + ``risk_band()`` instead of importing them from
``app.ml.calibration``. That vendoring can silently drift if someone re-tunes
the canonical cutpoints and forgets the copy. These tests fail CI on drift
(FIX #36) and lock in the None/NaN-aware raw-probability selection so a genuine
``p_exceed_raw`` of exactly 0.0 is no longer mislabelled via a truthiness ``or``
(FIX #37).
"""
from __future__ import annotations

import pandas as pd

from app.ml import calibration as canon
from scripts import bake_web_static as bake


# Every band boundary (and the values straddling it) so a missed cutpoint edit
# in either copy is caught.
_BAND_SWEEP = [
    0.0,
    0.1,
    0.19,
    0.20,
    0.25,
    0.29,
    0.30,
    0.5,
    0.69,
    0.70,
    0.85,
    1.0,
]


def test_vendored_thresholds_match_canonical():
    """FIX #36: each vendored threshold == its calibration.py counterpart."""
    assert bake._LOW_THRESHOLD == canon._LOW_THRESHOLD
    assert bake._HIGH_THRESHOLD == canon._HIGH_THRESHOLD
    assert bake._VERY_HIGH_THRESHOLD == canon._VERY_HIGH_THRESHOLD


def test_vendored_risk_band_matches_canonical_across_boundaries():
    """FIX #36: vendored risk_band() returns the same label as the canonical one
    across every band boundary."""
    for p in _BAND_SWEEP:
        assert bake.risk_band(p) == canon.risk_band(p), f"divergence at p={p}"


def test_zero_raw_probability_yields_low_not_high():
    """FIX #37: a genuine p_exceed_raw of exactly 0.0 under an active advisory
    must produce model_risk_band 'Low' (from 0.0), NOT 'High' (from the
    advisory-floored served p_exceed of 0.30). A truthiness ``or`` regressed
    this by letting 0.0 fall through to p_exceed."""
    fc_row = pd.Series(
        {
            "beach_id": "b1",
            "p_exceed_raw": 0.0,
            "p_exceed": 0.30,
            "risk_band": "Advisory",
        }
    )
    block = bake._build_forecast_block(fc_row, has_active_advisory=True)
    assert block["official_advisory_active"] is True
    assert block["risk_band"] == "Advisory"
    # The served band is overridden to "Advisory"; the underlying model band
    # must reflect the real 0.0 raw probability -> "Low".
    assert block["model_risk_band"] == "Low"


def test_raw_probability_preferred_over_floored_served_value():
    """A finite raw probability is always used in preference to the floored
    served p_exceed, regardless of magnitude."""
    fc_row = pd.Series(
        {"beach_id": "b2", "p_exceed_raw": 0.05, "p_exceed": 0.30}
    )
    block = bake._build_forecast_block(fc_row, has_active_advisory=True)
    assert block["model_risk_band"] == "Low"  # from 0.05, not 0.30


def test_missing_raw_falls_back_to_served_value():
    """When p_exceed_raw is absent/NaN, fall back to p_exceed."""
    fc_row = pd.Series(
        {"beach_id": "b3", "p_exceed_raw": float("nan"), "p_exceed": 0.30}
    )
    block = bake._build_forecast_block(fc_row, has_active_advisory=True)
    assert block["model_risk_band"] == "High"  # from the 0.30 fallback


def test_no_advisory_clears_model_band():
    """Without an active advisory the served band is the model band and
    model_risk_band is None (mirrors the repository override logic)."""
    fc_row = pd.Series(
        {"beach_id": "b4", "p_exceed_raw": 0.0, "p_exceed": 0.30}
    )
    block = bake._build_forecast_block(fc_row, has_active_advisory=False)
    assert block["official_advisory_active"] is False
    assert block["model_risk_band"] is None
