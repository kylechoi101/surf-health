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

import httpx
import pandas as pd

from app.data.pipeline.exceedance import compute_exceeds_stv

WQP_RESULT_URL = "https://www.waterqualitydata.us/data/Result/search"

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
    df["exceeds_stv"] = compute_exceeds_stv(df["value"], df["method"], df["units"], stv_threshold)
    df["data_source"] = "WQP"

    return df[_OUTPUT_COLUMNS].reset_index(drop=True)


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
