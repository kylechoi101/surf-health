"""County-name corrections for Beachwatch rows.

A few Beachwatch records carry an agency/jurisdiction name in the county
field instead of the actual county. Long Beach runs its own beach program,
so its stations arrive as county "Long Beach City" — but Long Beach is in
**Los Angeles County**. Remap so county-based grouping and filters are
correct.

Keep this table to unambiguous jurisdiction→county fixes only.
"""

from __future__ import annotations

import pandas as pd

COUNTY_CORRECTIONS: dict[str, str] = {
    "Long Beach City": "Los Angeles",
}


def correct_county(value):
    """Return the canonical county for ``value`` (or it unchanged).

    Passes through None/NaN. Trims surrounding whitespace before matching.
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return value
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return COUNTY_CORRECTIONS.get(text, text)


def correct_county_series(series: pd.Series) -> pd.Series:
    return series.map(correct_county)
