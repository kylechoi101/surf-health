"""Normalize + additively merge county-direct samples into observations.

``scripts/fetch_county_advisories.py`` scrapes county/city health departments
directly and persists every sample it sees to
``data/curated/county_direct_samples.parquet``. Until now that file was a
dead end: it fed the advisory/closure layer only, and nothing read the sample
rows, so the model and the "last sampled" recency shown in the apps saw none
of it.

That gap was county-visible. San Francisco publishes weekly results to its own
Socrata dataset (``data.sfgov.org`` resource ``v3fv-x3ux``) days after
sampling, but reports into the State Water Board — the route
``observations.parquet`` is built from — on a multi-week lag. Measured
2026-07-30: every state-routed source had **zero** SF rows for July while the
direct feed already held 07-06, 07-13, 07-20 and 07-27. SF's serving anchor sat
30 days stale next to an *active* 07-27 posting the advisory layer had already
published from the same underlying samples.

Why the merge key is the sample DATE, not ``sample_time``
---------------------------------------------------------
The state feed carries real collection times (``10:25:00``); the direct feed is
date-only. So the same physical sample hashes apart on ``sample_time``, and the
cross-source collapse in ``merge_live_into_observations`` — which keys on
``sample_time`` — would NOT catch it. Measured on the overlap window
(2026-04-20 .. 2026-06-30): all 206 state SF enterococcus rows match a direct
row on (beach_id, date) with an **identical** value, 206/206. Keying on
``sample_time`` would therefore have inserted 206 duplicate rows — the same
class of mirror bug that keying on ``method``/``units`` caused for the live
source, in a new guise.

So this module never merges on time and never displaces an existing row: a
direct row is dropped outright when ANY source already holds that
(beach_id, sample_date, analyte). The direct feed only ever fills gaps.

Scope
-----
Enterococcus only, matching the rest of the pipeline's label definition. The SF
feed also carries fecal coliform, and some SF postings are coliform-driven
(Baker Beach East, 07-27: COLI_FECAL 4200 with enterococcus at 10) — those stay
advisory-only by design, so the advisory and sample layers will not agree
beach-for-beach even after this merge.

Counties are allowlisted rather than taken wholesale. Only San Francisco has
had its overlap against the state feed measured; Sonoma and Humboldt are also
in the parquet but are themselves months stale (newest 2026-05-04 / 2026-05-11)
and report freshwater indicators, so admitting them would add unvalidated rows
for no recency gain.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.data.pipeline.beachwatch import _canonical_parameter
from app.data.pipeline.county_corrections import correct_county
from app.data.pipeline.exceedance import compute_exceeds_stv
from app.data.pipeline.units_corrections import correct_units_series
from app.data.pipeline.spelling import correct_place_spelling

DATA_SOURCE = "CountyDirect"

# Counties whose direct feed has been mirror-verified against the state route.
# See the module docstring before adding to this set.
INGEST_COUNTIES = frozenset({"San Francisco"})

# The feed reports MPN/100mL (see ``_SF_THRESHOLDS`` in
# scripts/fetch_county_advisories.py). Units matter: ``compute_exceeds_stv`` is
# method-aware and judges "copies" rows against the molecular threshold, so a
# culture row must declare culture units to be judged against the 104 STV.
UNITS = "MPN/100mL"
# The feed exposes no assay name. "unknown" is honest and reads as non-PCR,
# which is correct — SF's results are culture-based.
METHOD = "unknown"

# Mirror the live source's forecast-safety leeway rather than trusting dates.
MAX_FUTURE_DAYS = 2

# Canonical observations column order (matches observations.parquet).
_OBSERVATION_COLUMNS = [
    "beach_id", "sample_time", "sample_date", "analyte", "method", "units",
    "value", "exceeds_stv", "county", "station_name", "beach_name", "usepa_id",
    "weather", "storm_drain_flow", "tidal_height", "surf_height_observed",
    "turbidity_observed", "odor", "water_color", "data_source", "station_code",
]

_KEY = ["beach_id", "_d", "analyte"]


def normalize_county_direct_samples(
    raw: pd.DataFrame,
    stations: pd.DataFrame,
    stv_threshold: float,
    *,
    counties: frozenset[str] = INGEST_COUNTIES,
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """county_direct_samples rows -> canonical observations rows (enterococcus only)."""
    if raw.empty:
        return pd.DataFrame(columns=_OBSERVATION_COLUMNS)

    frame = raw.copy()
    frame["county"] = frame["county"].map(correct_county)
    frame = frame.loc[frame["county"].isin(counties)].copy()
    if frame.empty:
        print(f"[county-direct] no rows for allowlisted counties {sorted(counties)}")
        return pd.DataFrame(columns=_OBSERVATION_COLUMNS)

    frame["analyte"] = frame["analyte"].map(_canonical_parameter)
    frame = frame.loc[frame["analyte"] == "enterococcus"].copy()
    if frame.empty:
        return pd.DataFrame(columns=_OBSERVATION_COLUMNS)

    # beach_id is resolved upstream by the scraper's StationResolver; a row that
    # failed to resolve cannot be joined to history, so drop rather than guess.
    unresolved = int(frame["beach_id"].isna().sum())
    if unresolved:
        print(f"[county-direct] dropped {unresolved} rows with unresolved beach_id")
    frame = frame.loc[frame["beach_id"].notna()].copy()

    known = set(stations["beach_id"].dropna().astype(str)) if not stations.empty else set()
    orphan = ~frame["beach_id"].astype(str).isin(known)
    if int(orphan.sum()):
        print(
            f"[county-direct] dropped {int(orphan.sum())} rows whose beach_id is not in "
            f"beaches.parquet ({frame.loc[orphan, 'beach_id'].nunique()} distinct)"
        )
    frame = frame.loc[~orphan].copy()
    if frame.empty:
        return pd.DataFrame(columns=_OBSERVATION_COLUMNS)

    # Date-only feed: midnight is the honest stamp for "no collection time
    # reported", and matches how the live source handles an empty time cell.
    frame["sample_time"] = pd.to_datetime(frame["sample_date"], errors="coerce").dt.normalize()
    frame = frame.loc[frame["sample_time"].notna()].copy()

    horizon = (now or pd.Timestamp.utcnow().tz_localize(None)) + pd.Timedelta(days=MAX_FUTURE_DAYS)
    future = frame["sample_time"] > horizon
    if int(future.sum()):
        print(f"[county-direct] dropped {int(future.sum())} future-dated rows (> {horizon.date()})")
    frame = frame.loc[~future].copy()
    if frame.empty:
        return pd.DataFrame(columns=_OBSERVATION_COLUMNS)

    frame["sample_date"] = frame["sample_time"].dt.date
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    # Negative enterococcus is a "not analyzed" sentinel, never a count. Drop
    # rather than keep as NaN: a value-less row cannot carry a label, but it
    # could still win build_beach_day_frame's worst-sample collapse.
    frame.loc[frame["value"] < 0, "value"] = np.nan
    dropped_values = int(frame["value"].isna().sum())
    if dropped_values:
        print(f"[county-direct] dropped {dropped_values} rows with missing/negative values")
    frame = frame.loc[frame["value"].notna()].copy()
    if frame.empty:
        return pd.DataFrame(columns=_OBSERVATION_COLUMNS)

    frame["units"] = UNITS
    frame["method"] = METHOD
    # Source correction before the predicate reads them: a culture method
    # cannot report copies (see units_corrections), and is_pcr_measurement
    # would otherwise judge such a row against 1413 instead of 104.
    frame["units"] = correct_units_series(frame["method"], frame["units"])
    frame["exceeds_stv"] = compute_exceeds_stv(
        frame["value"], frame["method"], frame["units"], stv_threshold
    )

    lookup = (
        stations.dropna(subset=["beach_id"])
        .drop_duplicates("beach_id")
        .set_index("beach_id")
    )
    frame["station_code"] = frame["station_code"].astype(str).str.strip()
    frame["station_name"] = frame["station_code"].map(correct_place_spelling)
    frame["beach_name"] = (
        frame["beach_id"].map(lookup["beach_name"]).map(correct_place_spelling)
        if "beach_name" in lookup.columns
        else None
    )
    frame["usepa_id"] = (
        frame["beach_id"].map(lookup["usepa_id"]) if "usepa_id" in lookup.columns else None
    )
    # Observational extras the feed does not expose.
    for column in (
        "weather", "storm_drain_flow", "tidal_height",
        "surf_height_observed", "turbidity_observed", "odor", "water_color",
    ):
        frame[column] = None
    frame["data_source"] = DATA_SOURCE

    return frame[_OBSERVATION_COLUMNS].reset_index(drop=True)


def merge_county_direct_into_observations(
    observations: pd.DataFrame,
    direct: pd.DataFrame,
) -> pd.DataFrame:
    """Fold direct rows in, keeping every existing row untouched.

    Gap-fill only, keyed on (beach_id, sample_date, analyte) — see the module
    docstring for why the key is the date and not ``sample_time``. Any direct
    row whose beach-day another source already covers is discarded, so this can
    never displace, reorder, or duplicate ingested history.
    """
    if direct.empty:
        print("[county-direct] no usable rows; observations unchanged")
        return observations

    existing = observations.copy()
    if "data_source" not in existing.columns:
        existing["data_source"] = "BeachWatch"

    incoming = direct.copy()
    incoming["_d"] = pd.to_datetime(incoming["sample_time"], errors="coerce").dt.normalize()
    # One sample per station/day/analyte in this feed; collapse any repeat.
    before_intra = len(incoming)
    incoming = incoming.drop_duplicates(subset=_KEY, keep="first")
    intra = before_intra - len(incoming)

    if existing.empty:
        merged = incoming.drop(columns=["_d"])
    else:
        existing["_d"] = pd.to_datetime(existing["sample_time"], errors="coerce").dt.normalize()
        covered = set(
            map(tuple, existing.loc[:, _KEY].dropna(subset=["beach_id", "_d"]).to_numpy())
        )
        is_mirror = pd.Series(
            [tuple(row) in covered for row in incoming.loc[:, _KEY].to_numpy()],
            index=incoming.index,
        )
        merged = pd.concat(
            [existing, incoming.loc[~is_mirror]], ignore_index=True, sort=False
        ).drop(columns=["_d"])
        mirrors = int(is_mirror.sum())
        print(
            f"[county-direct] {mirrors} rows already held by another source (skipped), "
            f"{intra} intra-source repeats collapsed"
        )

    merged = merged.sort_values(["beach_id", "sample_time"]).reset_index(drop=True)
    print(
        f"[county-direct] merged: {len(observations)} -> {len(merged)} observations "
        f"(+{len(merged) - len(observations)} new samples)"
    )
    return merged
