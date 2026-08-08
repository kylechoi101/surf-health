"""Units corrections for enterococcus results — a source fix, not a predicate fix.

Three Mendocino rows arrive from the state export with method ``Enterolert``
(IDEXX Quanti-Tray defined-substrate, which yields **MPN** by construction) and
units ``Copies/100ml``:

    Hare Creek           2025-10-28   20
    Caspar Headlands SB  2024-10-08   10
    Pudding Creek Beach  2025-05-20   10

Because :func:`app.data.pipeline.exceedance.is_pcr_measurement` treats a
"copies" unit as sufficient evidence of a molecular method, those rows are
judged against the **1413** ddPCR action value instead of the 104 culture STV.
All three read ≤20, so no label moves today — but it is a live
silent-false-negative path: an Enterolert row at 500 MPN with this unit typo
would be published as clean.

**The predicate is not the bug.** The units arm of ``is_pcr_measurement``
exists precisely because some genuinely-molecular rows carry the unit but a
non-obvious method label, and narrowing it would change ``compute_exceeds_stv``
for real San Diego ddPCR rows — 17,033 of them. So this is corrected where
``county_corrections`` and ``spelling`` correct their data: at normalization,
on the way in.

It also matters for step 7. Post-step-4 the shipped frame makes "PCR exists in
2 counties" *true*, so a naive ``groupby(is_pcr)`` stratification would report a
"PCR regime" that silently means "San Diego + 3 Mendocino rows".

Scope is deliberately narrow and was measured before it was written: across all
503,766 stored observations, ``Copies/100ml`` occurs against exactly **one**
non-PCR method — ``Enterolert``, on 3 rows of 266,178. Every other culture
method is 100% MPN or CFU. The table below therefore lists culture assays whose
unit family is a property of the method itself (colony counts are CFU,
defined-substrate / most-probable-number assays are MPN), never a judgement
call, and it can never touch a row whose method names a molecular technique.
"""

from __future__ import annotations

import pandas as pd

# Normalized culture-method name -> the unit that method physically produces.
# Membrane-filtration / colony methods count colonies (CFU); defined-substrate
# and tube-dilution methods estimate a most-probable number (MPN).
CULTURE_METHOD_CANONICAL_UNITS: dict[str, str] = {
    "enterolert": "MPN/100ml",
    "colilert": "MPN/100ml",
    "colilert-18": "MPN/100ml",
    "mtf": "MPN/100ml",
    "mf": "CFU/100ml",
    "1600": "CFU/100ml",
    "epa 1600": "CFU/100ml",
    "1603": "CFU/100ml",
}

_COPIES_TOKEN = "copies"


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def correct_units(method: object, units: object) -> object:
    """Return the units for one row, correcting an impossible method/unit pair.

    A culture method cannot report copies. Anything else — including every
    molecular method, and every culture method not in the table — passes
    through untouched.
    """
    if _is_missing(units):
        return units
    text = str(units).strip()
    if _COPIES_TOKEN not in text.lower():
        return units
    if _is_missing(method):
        return units
    canonical = CULTURE_METHOD_CANONICAL_UNITS.get(str(method).strip().lower())
    return canonical if canonical is not None else units


def correct_units_series(method: pd.Series, units: pd.Series) -> pd.Series:
    """Vectorized :func:`correct_units` over aligned method/units columns."""
    if units.empty:
        return units
    corrected = [correct_units(m, u) for m, u in zip(method, units, strict=False)]
    return pd.Series(corrected, index=units.index, dtype=units.dtype)
