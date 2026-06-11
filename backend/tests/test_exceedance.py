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
