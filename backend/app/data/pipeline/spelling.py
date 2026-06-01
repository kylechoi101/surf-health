"""Hand-curated spelling corrections for Beachwatch place names.

Upstream Beachwatch station/beach names carry a handful of typos
("Tijana River", "Oceanisde Blvd", "storn drain", "oultet"). These are
display-only fixes applied to the name/beach_name/station_name fields during
normalization — the beach_id (a stable join/routing key) is left untouched
even when it embeds the misspelling.

Keep the table tight and whole-word: only unambiguous typos, never tokens
that could be a real or intentional spelling (e.g. Spanish "Cañon").
"""

from __future__ import annotations

import re

import pandas as pd

# wrong (lowercase) -> canonical replacement
SPELLING_CORRECTIONS: dict[str, str] = {
    "tijana": "Tijuana",
    "oceanisde": "Oceanside",
    "storn": "storm",
    "oultet": "outlet",
}

_PATTERNS = [
    (re.compile(rf"\b{re.escape(wrong)}\b", re.IGNORECASE), right)
    for wrong, right in SPELLING_CORRECTIONS.items()
]


def correct_place_spelling(text):
    """Return ``text`` with known place-name typos corrected (whole-word,
    case-insensitive). Passes through None/NaN unchanged."""
    if text is None:
        return None
    try:
        if pd.isna(text):
            return text
    except (TypeError, ValueError):
        pass
    out = str(text)
    for pattern, right in _PATTERNS:
        out = pattern.sub(right, out)
    return out


def correct_place_spelling_series(series: pd.Series) -> pd.Series:
    """Vectorized helper for a column of names."""
    return series.map(correct_place_spelling)
