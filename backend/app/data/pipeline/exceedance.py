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

    The single place in the codebase that maps a measurement method onto a
    threshold. Everything that needs to compare an enterococcus result to a
    number goes through here or through :func:`compute_exceeds_stv`, so the
    1413-vs-104 split cannot be forgotten at a new call site.
    """
    pcr = is_pcr_measurement(method, units)
    return pd.Series(
        np.where(pcr.to_numpy(), float(pcr_threshold), float(stv_threshold)),
        index=pcr.index,
        dtype="float64",
    )


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


# --------------------------------------------------------------------------
# Single-sample helpers.
#
# The API repositories hold one row at a time and used to re-derive exceedance
# with a bare ``latest_value > self.stv_threshold``. That is method-blind: a San
# Diego ddPCR reading of 800 copies/100mL is *below* its 1413 action value, yet
# it read as ~8x "the marine threshold" in the driver text shown to users, while
# ``exceeds_stv`` on the very same row said False. These wrappers delegate to
# the Series predicates above rather than restating them, so the two can never
# drift apart.
# --------------------------------------------------------------------------

CULTURE_ASSAY_LABEL = "culture"
PCR_ASSAY_LABEL = "ddPCR"


def _one(value: object) -> pd.Series:
    return pd.Series([value], dtype="object")


def is_pcr_sample(method: object, units: object) -> bool:
    """Whether one sample was measured by a molecular method."""
    return bool(is_pcr_measurement(_one(method), _one(units)).iloc[0])


def sample_action_value(
    method: object,
    units: object,
    stv_threshold: float,
    pcr_threshold: float = PCR_ENTEROCOCCUS_THRESHOLD_COPIES,
) -> float:
    """The action value one sample is judged against."""
    return float(action_value_for(_one(method), _one(units), stv_threshold, pcr_threshold).iloc[0])


def sample_exceeds_stv(
    value: object,
    method: object,
    units: object,
    stv_threshold: float,
    pcr_threshold: float = PCR_ENTEROCOCCUS_THRESHOLD_COPIES,
) -> bool:
    """Whether one sample exceeds the action value appropriate to its method."""
    numeric = pd.to_numeric(_one(value), errors="coerce")
    return bool(
        compute_exceeds_stv(numeric, _one(method), _one(units), stv_threshold, pcr_threshold).iloc[
            0
        ]
    )


def _format_number(value: float) -> str:
    return f"{value:g}"


def describe_sample_vs_action_value(
    value: object,
    method: object,
    units: object,
    stv_threshold: float,
    pcr_threshold: float = PCR_ENTEROCOCCUS_THRESHOLD_COPIES,
) -> str:
    """User-facing driver text naming the action value that actually applies.

    Never says "the marine threshold" unqualified: which threshold applies is
    the whole question for a ddPCR beach, and the reader cannot tell 104 from
    1413 from the number alone.
    """
    numeric = pd.to_numeric(_one(value), errors="coerce").iloc[0]
    pcr = is_pcr_sample(method, units)
    threshold = sample_action_value(method, units, stv_threshold, pcr_threshold)
    assay = PCR_ASSAY_LABEL if pcr else CULTURE_ASSAY_LABEL
    unit_text = str(units).strip() if units is not None and str(units).strip() else ""
    if pd.isna(numeric):
        return f"Latest official sample has no {assay} result to compare against the action value"
    reading = _format_number(float(numeric)) + (f" {unit_text}" if unit_text else "")
    exceeds = sample_exceeds_stv(value, method, units, stv_threshold, pcr_threshold)
    relation = "is above" if exceeds else "remains below"
    return (
        f"Latest official sample ({reading}) {relation} the "
        f"{_format_number(threshold)} {assay} action value"
    )
