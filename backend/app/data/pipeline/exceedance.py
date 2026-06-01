"""Method-aware enterococcus exceedance thresholds.

Most California Beachwatch stations report enterococcus by culture (colony)
methods — Enterolert/IDEXX (MPN), membrane filtration / EPA 1600 (CFU) — and
exceedance is judged against the EPA marine single-sample STV (104 per
``epa_marine_enterococcus_stv``).

San Diego County (Tijuana River / South Bay rapid program) reports many
samples by **digital PCR** (ddPCR, "MCB-ddPCR …"), measured in *copies/100mL*,
not CFU/MPN. PCR copy counts run far higher than culture counts for the same
water, so they MUST be judged against the molecular threshold (1413 copies),
not the 104 culture STV. Comparing copies against 104 false-flags almost every
PCR sample as an exceedance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Molecular (qPCR/ddPCR) enterococcus exceedance threshold, in copies/100mL.
PCR_ENTEROCOCCUS_THRESHOLD_COPIES: float = 1413.0


def is_pcr_measurement(method: pd.Series, units: pd.Series) -> pd.Series:
    """Boolean mask: rows measured by a molecular (PCR) method.

    Detected by a "pcr" substring in the analysis method (ddPCR,
    MCB-ddPCR, qPCR) OR a "copies" unit — either alone is sufficient, since
    some rows carry the unit but a non-obvious method label.
    """
    by_method = method.astype(str).str.contains("pcr", case=False, na=False)
    by_units = units.astype(str).str.contains("copies", case=False, na=False)
    return by_method | by_units


def compute_exceeds_stv(
    value: pd.Series,
    method: pd.Series,
    units: pd.Series,
    stv_threshold: float,
    pcr_threshold: float = PCR_ENTEROCOCCUS_THRESHOLD_COPIES,
) -> pd.Series:
    """Per-row exceedance flag using the threshold appropriate to the method.

    PCR rows are judged against ``pcr_threshold`` (copies); all others against
    the culture ``stv_threshold``. Strictly greater-than, matching the prior
    ``value.gt(stv_threshold)`` semantics. NaN values never exceed.
    """
    pcr = is_pcr_measurement(method, units).to_numpy()
    threshold = np.where(pcr, pcr_threshold, stv_threshold)
    exceeds = value.fillna(0).to_numpy() > threshold
    return pd.Series(exceeds, index=value.index)
