"""Station-quality gating for the curated roster.

Many Beachwatch stations were stood up for a single one-time incident (a
spill, a complaint) and sampled once or a handful of times within a short
window, then never again. Treating them as monitored beaches surfaces stale,
misleading 'beta' coverage and feeds noise into the model.

A station must have a sampling history spanning at least
``MIN_SAMPLING_SPAN_DAYS`` to be supported; shorter histories are capped to
'unsupported' (still discoverable, no forecast, excluded from training).
"""

from __future__ import annotations

import pandas as pd

# Minimum span (first→last sample) for a station to count as ongoing
# monitoring rather than a one-time incident.
MIN_SAMPLING_SPAN_DAYS = 90

# Minimum observations for the model-backed 'production' tier (legacy rule).
PRODUCTION_MIN_OBSERVATIONS = 10


def support_status_for(
    observation_count: float,
    sampling_span_days: float | None,
    min_span_days: int = MIN_SAMPLING_SPAN_DAYS,
) -> str:
    """Return 'unsupported' | 'beta' | 'production' for a station.

    A sampling history shorter than ``min_span_days`` (or missing) is a
    one-time/short-incident station → 'unsupported', regardless of count.
    Otherwise the legacy observation-count rule decides production vs beta.
    """
    if sampling_span_days is None or pd.isna(sampling_span_days) or sampling_span_days < min_span_days:
        return "unsupported"
    return "production" if observation_count >= PRODUCTION_MIN_OBSERVATIONS else "beta"
