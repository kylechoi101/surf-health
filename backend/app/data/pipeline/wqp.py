"""EPA Water Quality Portal (WQP) connector — national beach enterococcus data.

WQP (waterqualitydata.us) is the programmatic source behind EPA BEACON: every
US coastal state submits beach monitoring results to WQX, and WQP serves them
in a single standardized schema. CEDEN (already ingested) is California's feed
into the same system — so WQP is the national superset, useful for training a
model that generalizes ACROSS counties/states rather than memorizing CA.

This module normalizes the WQX result schema into the same shape as the
BeachWatch/CEDEN observations, harmonizing the exceedance label through the
method-aware threshold layer (culture 104 STV vs PCR 1413 copies).
"""

from __future__ import annotations

import re

import httpx
import pandas as pd

from app.data.pipeline.exceedance import compute_exceeds_stv
from app.data.pipeline.units_corrections import correct_units_series
from app.data.pipeline.station_quality import support_status_for

WQP_RESULT_URL = "https://www.waterqualitydata.us/data/Result/search"

# US coastal + Great Lakes states/territories (BEACH Act beach-monitoring
# reporters), as WQP FIPS state codes. Used to pool a national training set.
COASTAL_STATE_FIPS = [
    "US:01", "US:02", "US:06", "US:09", "US:10", "US:12", "US:13", "US:15",
    "US:17", "US:18", "US:22", "US:23", "US:24", "US:25", "US:26", "US:27",
    "US:28", "US:33", "US:34", "US:36", "US:37", "US:39", "US:41", "US:42",
    "US:44", "US:45", "US:48", "US:51", "US:53", "US:55", "US:72",
]

_STATION_COLUMNS = [
    "beach_id",
    "station_id",
    "name",
    "county",
    "region",
    "latitude",
    "longitude",
    "support_status",
]


def _wqp_beach_id(state_fips: str, station_id: str) -> str:
    """Stable, namespaced beach_id for a WQP station — ``wqp-<state>-<slug>``
    so it can never collide with the California BeachWatch ids."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(station_id).lower()).strip("-")
    st = str(state_fips or "").replace("US:", "us").lower() or "us"
    return f"wqp-{st}-{slug}"[:120]


def build_wqp_stations(observations: pd.DataFrame) -> pd.DataFrame:
    """Derive a national station roster from normalized WQP observations.

    One row per station with median coordinates and a support_status from the
    same duration cap used for California (a sampling span < 90 days is a
    one-time/short-incident station → unsupported).
    """
    if observations.empty:
        return pd.DataFrame(columns=_STATION_COLUMNS)

    rows = []
    for sid, sub in observations.groupby("station_id"):
        state = str(sub["state_fips"].iloc[0]) if "state_fips" in sub.columns else ""
        times = pd.to_datetime(sub["sample_time"], errors="coerce").dropna()
        span = int((times.max() - times.min()).days) if len(times) else 0
        rows.append(
            {
                "beach_id": _wqp_beach_id(state, sid),
                "station_id": str(sid),
                "name": str(sid),
                "county": None,
                "region": state,
                "latitude": float(sub["latitude"].median()),
                "longitude": float(sub["longitude"].median()),
                "support_status": support_status_for(len(sub), span),
            }
        )
    return pd.DataFrame(rows, columns=_STATION_COLUMNS)

# WQX column names -> our fields.
_VALUE_COL = "ResultMeasureValue"
_UNIT_COL = "ResultMeasure/MeasureUnitCode"
_METHOD_COL = "ResultAnalyticalMethod/MethodName"
_CHAR_COL = "CharacteristicName"
_STATION_COL = "MonitoringLocationIdentifier"
_DATE_COL = "ActivityStartDate"
_TIME_COL = "ActivityStartTime/Time"
_LAT_COL = "ActivityLocation/LatitudeMeasure"
_LON_COL = "ActivityLocation/LongitudeMeasure"

_OUTPUT_COLUMNS = [
    "station_id",
    "sample_time",
    "sample_date",
    "analyte",
    "method",
    "units",
    "value",
    "exceeds_stv",
    "latitude",
    "longitude",
    "data_source",
]


def _col(frame: pd.DataFrame, name: str) -> pd.Series:
    if name in frame.columns:
        return frame[name]
    return pd.Series([None] * len(frame), index=frame.index)


def normalize_wqp_results(frame: pd.DataFrame, stv_threshold: float) -> pd.DataFrame:
    """Map a WQX result frame to the curated observation schema.

    Keeps only enterococcus rows with a non-negative numeric value, applies the
    method-aware exceedance threshold, and parses station/coords/date.
    """
    if frame.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    df = frame.copy()
    char = _col(df, _CHAR_COL).astype(str).str.lower()
    df = df.loc[char.str.contains("enteroc", na=False)].copy()
    if df.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    df["value"] = pd.to_numeric(_col(df, _VALUE_COL), errors="coerce")
    # Enterococcus is a non-negative count; drop invalid/negative sentinels.
    df = df.loc[df["value"].notna() & (df["value"] >= 0)].copy()
    if df.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    df["units"] = _col(df, _UNIT_COL).fillna("unknown").astype(str).str.strip()
    df["method"] = _col(df, _METHOD_COL).fillna("unknown").astype(str).str.strip()
    df["analyte"] = "enterococcus"
    df["station_id"] = _col(df, _STATION_COL).astype(str)

    date = pd.to_datetime(_col(df, _DATE_COL), errors="coerce")
    time = _col(df, _TIME_COL).fillna("").astype(str)
    combined = date.dt.strftime("%Y-%m-%d") + " " + time.where(time.str.len() > 0, "00:00:00")
    df["sample_time"] = pd.to_datetime(combined, errors="coerce").fillna(date)
    df["sample_date"] = df["sample_time"].dt.date

    df["latitude"] = pd.to_numeric(_col(df, _LAT_COL), errors="coerce")
    df["longitude"] = pd.to_numeric(_col(df, _LON_COL), errors="coerce")
    # Source correction before the predicate reads them: a culture method
    # cannot report copies (see units_corrections), and is_pcr_measurement
    # would otherwise judge such a row against 1413 instead of 104.
    df["units"] = correct_units_series(df["method"], df["units"])
    df["exceeds_stv"] = compute_exceeds_stv(df["value"], df["method"], df["units"], stv_threshold)
    df["data_source"] = "WQP"

    return df[_OUTPUT_COLUMNS].reset_index(drop=True)


# CA-side observed columns that BeachWatch carries but WQP does not — added as
# null so the national frame is schema-compatible with build_beach_day_frame.
_BEACHWATCH_ONLY_OBS_COLS = [
    "weather", "storm_drain_flow", "tidal_height", "surf_height_observed",
    "turbidity_observed", "odor", "water_color", "analyte", "units", "method",
    "county", "station_name", "beach_name", "usepa_id", "station_code",
]


def fetch_national_wqp(
    states: list[str],
    start: str,
    end: str,
    stv_threshold: float,
    *,
    client: httpx.Client | None = None,
) -> pd.DataFrame:
    """Fetch + normalize WQP enterococcus for many states, tagged by state.

    Per-state failures are logged and skipped so one flaky state can't abort the
    national pool. Returns concatenated normalized observations.
    """
    owns = client is None
    client = client or httpx.Client(timeout=300.0, follow_redirects=True)
    frames: list[pd.DataFrame] = []
    try:
        for st in states:
            try:
                raw = fetch_wqp_results(st, start, end, client=client)
                norm = normalize_wqp_results(raw, stv_threshold)
                if not norm.empty:
                    norm["state_fips"] = st
                    frames.append(norm)
                    print(f"[wqp] {st}: {len(norm)} enterococcus obs")
            except Exception as exc:  # noqa: BLE001 - one state must not abort the pool
                print(f"[wqp] {st} failed: {type(exc).__name__}: {str(exc)[:120]}")
    finally:
        if owns:
            client.close()
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def to_beach_day_observations(national_obs: pd.DataFrame) -> pd.DataFrame:
    """Shape national WQP observations to match build_beach_day_frame's input:
    rename value->kept, add the BeachWatch-only observed columns as null, and
    map station_id -> beach_id."""
    if national_obs.empty:
        return national_obs
    df = national_obs.copy()
    df["beach_id"] = [
        _wqp_beach_id(str(s), str(sid))
        for s, sid in zip(df.get("state_fips", ""), df["station_id"], strict=False)
    ]
    for col in _BEACHWATCH_ONLY_OBS_COLS:
        if col not in df.columns:
            df[col] = None
    df["analyte"] = "enterococcus"
    return df


def fetch_wqp_results(
    statecode: str,
    start: str,
    end: str,
    *,
    client: httpx.Client | None = None,
) -> pd.DataFrame:
    """Fetch raw WQX enterococcus results for a state + date range (CSV).

    ``statecode`` is a FIPS code like ``US:06`` (CA), ``US:12`` (FL).
    Dates are ``MM-DD-YYYY`` per the WQP API.
    """
    params = {
        "statecode": statecode,
        "characteristicName": "Enterococcus",
        "startDateLo": start,
        "startDateHi": end,
        "mimeType": "csv",
        "dataProfile": "resultPhysChem",
        "providers": "STORET",
    }
    owns = client is None
    client = client or httpx.Client(timeout=120.0, follow_redirects=True)
    try:
        resp = client.get(WQP_RESULT_URL, params=params)
        resp.raise_for_status()
        from io import StringIO

        return pd.read_csv(StringIO(resp.text), dtype=str, low_memory=False)
    finally:
        if owns:
            client.close()
