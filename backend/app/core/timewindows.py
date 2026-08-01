"""The forecast-safe daily cutoff.

Every daily environmental summary is aggregated over the 24 hours ENDING at
5 AM PT, so nothing from the morning of the sample can leak into a feature
predicting that sample. This one rule had four byte-identical copies
(``precipitation``, ``hydrology``, ``solar_wind``, ``forecast_weather``) — a
core invariant of the product with no single definition to point at.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

PACIFIC = ZoneInfo("America/Los_Angeles")

# The hour (PT) at which a forecast day's aggregation window closes.
FORECAST_CUTOFF_HOUR_PT = 5


def forecast_cutoff_utc(d: date) -> pd.Timestamp:
    """5 AM PT on ``d``, in UTC — correctly handling PST vs PDT."""
    return pd.Timestamp(
        datetime(d.year, d.month, d.day, FORECAST_CUTOFF_HOUR_PT, 0, 0, tzinfo=PACIFIC)
    ).tz_convert("UTC")
