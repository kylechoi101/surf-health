import numpy as np
import pandas as pd

from app.data.pipeline.exceedance import (
    PCR_ENTEROCOCCUS_THRESHOLD_COPIES,
    is_pcr_measurement,
    compute_exceeds_stv,
)


def test_pcr_detected_by_method_or_units():
    method = pd.Series(["Enterolert", "ddPCR", "MCB-ddPCR SOP018-000", "1600", "unknown"])
    units = pd.Series(["MPN/100ml", "Copies/100ml", "copies/100 mL", "CFU/100ml", "Copies/100ml"])
    pcr = is_pcr_measurement(method, units)
    # ddPCR / MCB-ddPCR by method; row 4 (unknown method) flagged by copies units.
    assert pcr.tolist() == [False, True, True, False, True]


def test_colony_uses_stv_threshold():
    value = pd.Series([200.0, 50.0, 104.0])  # > / < / == 104
    method = pd.Series(["Enterolert"] * 3)
    units = pd.Series(["MPN/100ml"] * 3)
    out = compute_exceeds_stv(value, method, units, stv_threshold=104.0)
    # strictly greater than threshold (matches existing .gt semantics)
    assert out.tolist() == [True, False, False]


def test_pcr_uses_copies_threshold_not_stv():
    # 500 copies exceeds the colony STV (104) but is BELOW the PCR threshold (1413).
    value = pd.Series([500.0, 2000.0, 1413.0])
    method = pd.Series(["ddPCR", "ddPCR", "ddPCR"])
    units = pd.Series(["Copies/100ml"] * 3)
    out = compute_exceeds_stv(value, method, units, stv_threshold=104.0)
    assert out.tolist() == [False, True, False]
    assert PCR_ENTEROCOCCUS_THRESHOLD_COPIES == 1413.0


def test_mixed_frame_applies_threshold_per_row():
    value = pd.Series([500.0, 500.0])
    method = pd.Series(["ddPCR", "Enterolert"])
    units = pd.Series(["Copies/100ml", "MPN/100ml"])
    out = compute_exceeds_stv(value, method, units, stv_threshold=104.0)
    # Same numeric value: PCR row stays under 1413 (False); colony row over 104 (True).
    assert out.tolist() == [False, True]


def test_nan_value_does_not_exceed():
    value = pd.Series([np.nan])
    method = pd.Series(["ddPCR"])
    units = pd.Series(["Copies/100ml"])
    out = compute_exceeds_stv(value, method, units, stv_threshold=104.0)
    assert out.tolist() == [False]


def test_preserves_index():
    value = pd.Series([200.0, 50.0], index=[7, 9])
    method = pd.Series(["Enterolert", "Enterolert"], index=[7, 9])
    units = pd.Series(["MPN/100ml", "MPN/100ml"], index=[7, 9])
    out = compute_exceeds_stv(value, method, units, stv_threshold=104.0)
    assert list(out.index) == [7, 9]


def test_pcr_threshold_regression_copies_vs_culture():
    """Headline data-quality correction: the SAME numeric value must be judged
    against 1413 for PCR/copies and against 104 for culture.

    1200 copies is chosen because it straddles both thresholds: it is BELOW the
    PCR threshold (1413) so a correct PCR path returns False, but ABOVE the
    culture STV (104) so a buggy flat-104 path would have falsely flagged it.
    The same 1200 reported by culture must exceed (1200 > 104).
    """
    # PCR (MCB-ddPCR / copies): 1200 copies must NOT exceed under the 1413 threshold.
    pcr_out = compute_exceeds_stv(
        pd.Series([1200.0]),
        pd.Series(["MCB-ddPCR SOP018-000"]),
        pd.Series(["Copies/100ml"]),
        stv_threshold=104.0,
    )
    assert pcr_out.tolist() == [False], "1200 copies must be judged against 1413, not 104"

    # The identical numeric value reported by a culture method MUST exceed under 104.
    culture_out = compute_exceeds_stv(
        pd.Series([1200.0]),
        pd.Series(["Enterolert"]),
        pd.Series(["MPN/100ml"]),
        stv_threshold=104.0,
    )
    assert culture_out.tolist() == [True], "1200 MPN must exceed the 104 culture STV"


def test_pcr_above_molecular_threshold_exceeds():
    """A PCR sample above 1413 copies still exceeds (proves the PCR path isn't
    swallowing every PCR row)."""
    out = compute_exceeds_stv(
        pd.Series([1500.0]),
        pd.Series(["MCB-ddPCR SOP018-000"]),
        pd.Series(["Copies/100ml"]),
        stv_threshold=104.0,
    )
    assert out.tolist() == [True]


def test_culture_150_cfu_exceeds_under_104():
    """A 150 CFU culture sample exceeds the 104 marine STV."""
    out = compute_exceeds_stv(
        pd.Series([150.0]),
        pd.Series(["EPA 1600"]),
        pd.Series(["CFU/100ml"]),
        stv_threshold=104.0,
    )
    assert out.tolist() == [True]


# --- The consumer side: the persistence baseline must honour the same rule -----
#
# The 104-vs-1413 split used to stop at the ingest boundary. training's
# persistence baseline re-derived exceedance from the raw value against a flat
# 104, so San Diego ddPCR copy counts in (104, 1413] — already labelled CLEAN by
# compute_exceeds_stv — produced a persistence positive, which the serve path
# then hard-pinned to 1.0. On 2026-07-30 that put 34 of the 74 served "High"
# bands on beaches whose most recent lab result was clean. These tests pin the
# fix at both ends.
#
# The serve path no longer pins (2026-08-06): a persistence positive now drives a
# post-calibration floor at _LOW_THRESHOLD, so the same mistake costs a Moderate
# band rather than a certainty. The blast radius shrank; the rule did not change,
# and persistence is still the baseline every promotion gate scores against.


def test_exceedance_last_obs_feature_carries_the_method_aware_decision():
    """features builds exceeds_stv_last_obs by the same shift(1).ffill() rule as
    the *_last_obs values, so it is forecast-safe and never sees its own row."""
    from app.data.pipeline.features import add_temporal_features

    frame = pd.DataFrame(
        {
            "beach_id": ["b1"] * 4,
            "sample_date": pd.to_datetime(
                ["2026-01-01", "2026-01-08", "2026-01-15", "2026-01-22"]
            ),
            # A clean PCR row (298 copies) sits at index 1.
            "enterococcus_value": [50.0, 298.0, 60.0, 70.0],
            "exceeds_stv": [0.0, 0.0, 1.0, 0.0],
        }
    )
    enriched = add_temporal_features(frame)
    last = enriched["exceeds_stv_last_obs"].tolist()

    assert pd.isna(last[0]), "first row of a beach has no prior observation"
    assert last[1] == 0.0, "carries row 0's clean result, not its own"
    assert last[2] == 0.0, "the 298-copy PCR row was CLEAN — must not carry a 1"
    assert last[3] == 1.0, "carries row 2's genuine exceedance"


def test_persistence_baseline_does_not_fire_on_clean_pcr_row():
    """The regression that shipped 34 false 'High' bands: a clean 298-copy ddPCR
    result must not become a persistence positive."""
    from app.ml.training import _persistence_probabilities

    features = pd.DataFrame(
        {
            # Both rows carry a last-observed value above the 104 culture STV.
            "enterococcus_value_last_obs": [298.0, 298.0],
            # Row 0 was ddPCR copies/100mL -> clean (298 < 1413).
            # Row 1 was a culture method   -> exceedance (298 > 104).
            "exceeds_stv_last_obs": [0.0, 1.0],
        }
    )
    probs = _persistence_probabilities(features, 104.0)

    assert probs.tolist() == [0.0, 1.0], (
        "persistence must carry the method-aware exceedance decision forward, "
        "not re-threshold the raw value against the culture STV"
    )


def test_persistence_baseline_falls_back_when_feature_absent():
    """Frames built before exceeds_stv_last_obs existed keep the legacy rule."""
    from app.ml.training import _persistence_probabilities

    legacy = pd.DataFrame({"enterococcus_value_last_obs": [50.0, 150.0]})
    assert _persistence_probabilities(legacy, 104.0).tolist() == [0.0, 1.0]

    empty = pd.DataFrame({"other_column": [1.0, 2.0]})
    assert _persistence_probabilities(empty, 104.0).tolist() == [0.0, 0.0]
