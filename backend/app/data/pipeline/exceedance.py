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


def action_value_for(
    method: pd.Series,
    units: pd.Series,
    stv_threshold: float,
    pcr_threshold: float = PCR_ENTEROCOCCUS_THRESHOLD_COPIES,
) -> pd.Series:
    """Per-row action value: the number this row's result is judged against.

    The single place that maps a measurement method onto a threshold, so the
    1413-vs-104 split cannot be forgotten at a new call site. Extracted from
    :func:`compute_exceeds_stv` (which now delegates here) because the same map
    is needed to put values from the two assays on one comparable scale — see
    :func:`action_value_ratio`.
    """
    pcr = is_pcr_measurement(method, units)
    return pd.Series(
        np.where(pcr.to_numpy(), float(pcr_threshold), float(stv_threshold)),
        index=pcr.index,
        dtype="float64",
    )


def action_value_ratio(
    value: pd.Series,
    method: pd.Series,
    units: pd.Series,
    stv_threshold: float,
    pcr_threshold: float = PCR_ENTEROCOCCUS_THRESHOLD_COPIES,
) -> pd.Series:
    """Enterococcus result expressed as a multiple of its OWN action value.

    ``1.0`` means "exactly at the action value" whichever assay produced the
    number: a culture result of 104 MPN/100mL and a ddPCR result of 1413
    copies/100mL both map to 1.0. This is the only scale on which two rows from
    different assays may be compared, averaged, or lagged against each other.

    Why it exists: ``beach_day.enterococcus_value`` mixes MPN/CFU and
    copies/100mL in one numeric column, and every value-derived model feature
    (``*_lag_*``, ``*_last_obs``, the rolling geomeans) is built from it. A
    same-assay flag cannot repair that, because a lag holds a *previous* row's
    value while any assay flag describes the *current* row — so on a beach that
    switched assays the model sees a ~300x step change with no input that
    explains it. Normalising the stored quantity removes the discontinuity at
    the source instead of trying to annotate it downstream.

    The exceedance decision is deliberately NOT re-derived from this: it stays
    with :func:`compute_exceeds_stv` on the raw value. The two agree by
    construction (``ratio > 1.0`` iff ``exceeds_stv``), and that identity is
    pinned by a test.
    """
    numeric = pd.to_numeric(value, errors="coerce")
    threshold = action_value_for(method, units, stv_threshold, pcr_threshold)
    return numeric / threshold.to_numpy()


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
    threshold = action_value_for(method, units, stv_threshold, pcr_threshold).to_numpy()
    exceeds = value.fillna(0).to_numpy() > threshold
    return pd.Series(exceeds, index=value.index)
