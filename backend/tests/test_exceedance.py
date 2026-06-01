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
