"""Normalize + additively merge live-BeachWatch results into observations.

Companion to ``app.data.connectors.beachwatch_live`` (see that module for why the
live app exists and what it does/doesn't cover). This module turns its raw HTML
table into the canonical observations schema and folds it in WITHOUT displacing
anything already ingested.

Two deliberate departures from ``normalize_bacteria_results``:

1. **beach_id comes from a station_code join, not ``derive_beach_id``.** The live
   app does not return ``USEPAID``, which is the first slug component, so
   re-deriving would mint ids that match nothing and orphan every row from its
   own history. All 605 live stations matched ``beaches.parquet.station_code``
   when measured, so the join is the reliable path — and any station we cannot
   map is dropped rather than guessed at.
2. **No ``is_marine_station`` filter.** That gate reads ``WaterBodyClass`` /
   ``WaterBodyType``, neither of which the live app returns, so it would filter
   everything to zero. Joining against beaches we already serve is a strictly
   tighter filter anyway.

Exceedance uses the shared method-aware ``compute_exceeds_stv`` — San Diego's
MCB-ddPCR reports Copies/100ml and must be judged against the molecular
threshold, not the 104 culture STV.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.data.pipeline.beachwatch import _canonical_parameter
from app.data.pipeline.ceden import _normalize_method_or_unit
from app.data.pipeline.county_corrections import correct_county
from app.data.pipeline.exceedance import compute_exceeds_stv
from app.data.pipeline.units_corrections import correct_units_series
from app.data.pipeline.spelling import correct_place_spelling

DATA_SOURCE = "BeachWatch.Live"

# The live app serves rows dated months ahead (14 rows dated 2026-10-02 observed
# on 2026-07-29, Long Beach City). Mirror the pipeline's own forecast-safety
# leeway rather than trusting the source.
MAX_FUTURE_DAYS = 2

_OBSERVATION_COLUMNS = [
    "beach_id", "sample_time", "sample_date", "analyte", "method", "units",
    "value", "exceeds_stv", "county", "station_name", "beach_name", "usepa_id",
    "weather", "storm_drain_flow", "tidal_height", "surf_height_observed",
    "turbidity_observed", "odor", "water_color", "data_source", "station_code",
]


def normalize_live_results(
    raw: pd.DataFrame,
    stations: pd.DataFrame,
    stv_threshold: float,
    *,
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Raw live-app table -> canonical observations rows (enterococcus only)."""
    if raw.empty:
        return pd.DataFrame(columns=_OBSERVATION_COLUMNS)

    frame = raw.copy()
    frame["analyte"] = frame["parameter"].map(_canonical_parameter)
    frame = frame.loc[frame["analyte"] == "enterococcus"].copy()
    if frame.empty:
        return pd.DataFrame(columns=_OBSERVATION_COLUMNS)

    frame["station_code"] = frame["station_code"].astype(str).str.strip()
    lookup = (
        stations.dropna(subset=["station_code"])
        .assign(station_code=lambda d: d["station_code"].astype(str).str.strip())
        .drop_duplicates("station_code")
        .set_index("station_code")
    )
    frame["beach_id"] = frame["station_code"].map(lookup["beach_id"])
    unmapped = int(frame["beach_id"].isna().sum())
    if unmapped:
        print(
            f"[beachwatch-live] dropped {unmapped} rows with unmappable station_code "
            f"({frame.loc[frame['beach_id'].isna(), 'station_code'].nunique()} distinct)"
        )
    frame = frame.loc[frame["beach_id"].notna()].copy()
    if frame.empty:
        return pd.DataFrame(columns=_OBSERVATION_COLUMNS)

    stamp = (
        frame["sample_date"].astype(str).str.strip()
        + " "
        + frame["sample_time_raw"].astype(str).str.strip().replace("", "00:00:00")
    )
    frame["sample_time"] = pd.to_datetime(stamp, errors="coerce")
    frame = frame.loc[frame["sample_time"].notna()].copy()

    horizon = (now or pd.Timestamp.utcnow().tz_localize(None)) + pd.Timedelta(days=MAX_FUTURE_DAYS)
    future = frame["sample_time"] > horizon
    if int(future.sum()):
        print(f"[beachwatch-live] dropped {int(future.sum())} future-dated rows (> {horizon.date()})")
    frame = frame.loc[~future].copy()
    if frame.empty:
        return pd.DataFrame(columns=_OBSERVATION_COLUMNS)

    frame["sample_date"] = frame["sample_time"].dt.date
    frame["value"] = pd.to_numeric(frame["result"], errors="coerce")
    # Negative enterococcus is a "not analyzed" sentinel (-999/-1000), never a count.
    frame.loc[frame["value"] < 0, "value"] = np.nan
    frame["units"] = frame["unit"].fillna("unknown").astype(str).str.strip()
    frame["method"] = frame["method"].fillna("unknown").astype(str).str.strip()
    # Source correction before the predicate reads them: a culture method
    # cannot report copies (see units_corrections), and is_pcr_measurement
    # would otherwise judge such a row against 1413 instead of 104.
    frame["units"] = correct_units_series(frame["method"], frame["units"])
    frame["exceeds_stv"] = compute_exceeds_stv(
        frame["value"], frame["method"], frame["units"], stv_threshold
    )
    frame["county"] = frame["county"].map(correct_county)
    frame["station_name"] = frame["station_code"].map(correct_place_spelling)
    frame["beach_name"] = frame["beach_name"].map(correct_place_spelling)
    frame["usepa_id"] = frame["beach_id"].map(lookup.reset_index().set_index("beach_id")["usepa_id"]) \
        if "usepa_id" in lookup.columns else None
    # Observational extras the live app does not expose.
    for column in (
        "weather", "storm_drain_flow", "tidal_height",
        "surf_height_observed", "turbidity_observed", "odor", "water_color",
    ):
        frame[column] = None
    frame["data_source"] = DATA_SOURCE

    return frame[_OBSERVATION_COLUMNS].reset_index(drop=True)


def merge_live_into_observations(
    observations: pd.DataFrame,
    live: pd.DataFrame,
) -> pd.DataFrame:
    """Fold live rows in, keeping every existing row.

    Two passes, mirroring ``merge_ceden_into_beachwatch_bundle``:

    1. **Intra-source**: dedupe on (beach_id, sample_time, analyte, data_source,
       method, units, value). Method and units are IN the key on purpose — two
       genuinely different assays on one sample are two observations.
    2. **Cross-source mirrors**: group on (beach_id, sample_time, analyte, value)
       WITHOUT method/units/source. If a group spans >1 source it is the same
       physical sample reported twice, so collapse it to the highest-priority row.

    Pass 2 is not optional, and normalizing the method string is NOT a substitute
    for it: the sources spell the same assay differently ("1600" vs "EPA 1600"),
    and ``_normalize_method_or_unit`` only strips non-alphanumerics, so those
    still hash apart ("1600" vs "epa1600"). Without pass 2 a one-month window
    inserted ~800 duplicate rows and a 4-year backfill inserted ~31,000.
    """
    if live.empty:
        return observations
    existing = observations.copy()
    if "data_source" not in existing.columns:
        existing["data_source"] = "BeachWatch"

    combined = pd.concat([existing, live], ignore_index=True, sort=False)
    # Existing sources outrank live; ties inside a source fall back to first seen.
    priority = {
        "BeachWatch": 0,
        "BeachWatch.SafeToSwim": 1,
        "CEDEN.SafeToSwim": 2,
        "Central Valley Water Board.SafeToSwim": 3,
        DATA_SOURCE: 8,
    }
    combined["_priority"] = combined["data_source"].map(priority).fillna(9)
    combined["_t"] = pd.to_datetime(combined["sample_time"], errors="coerce")
    combined["_v"] = pd.to_numeric(combined["value"], errors="coerce").round(6)
    combined["_m"] = combined["method"].map(_normalize_method_or_unit)
    combined["_u"] = combined["units"].map(_normalize_method_or_unit)

    before = len(existing)
    # Sort by priority FIRST so every keep="first" below retains the
    # highest-priority source; drop_duplicates preserves order, so the ordering
    # established here still holds when pass 2 runs.
    combined = combined.sort_values(["_priority", "_t"]).drop_duplicates(
        subset=["beach_id", "_t", "analyte", "data_source", "_m", "_u", "_v"], keep="first"
    )
    # Pass 2 — collapse the same physical sample reported by >1 source.
    mirror_sources = combined.groupby(["beach_id", "_t", "analyte", "_v"])["data_source"].transform(
        "nunique"
    )
    is_mirrored = mirror_sources.gt(1).fillna(False)
    mirrored = combined.loc[is_mirrored].drop_duplicates(
        subset=["beach_id", "_t", "analyte", "_v"], keep="first"
    )
    collapsed = int(is_mirrored.sum() - len(mirrored))
    combined = (
        pd.concat([combined.loc[~is_mirrored], mirrored], ignore_index=True, sort=False)
        .drop(columns=["_priority", "_t", "_v", "_m", "_u"])
        .sort_values(["beach_id", "sample_time"])
        .reset_index(drop=True)
    )
    added = len(combined) - before
    print(
        f"[beachwatch-live] merged: {before} -> {len(combined)} observations "
        f"(+{added} new samples, {collapsed} cross-source mirrors collapsed)"
    )
    return combined
