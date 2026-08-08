from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd

from app.data.pipeline.beachwatch import build_beach_day_frame
from app.data.pipeline.exceedance import compute_exceeds_stv
from app.data.pipeline.units_corrections import correct_units_series
from app.data.pipeline.external_covariates import haversine_km


ENTEROCOCCUS_TERMS = {"enterococcus", "enterococci", "entero", "enterococus"}
CEDEN_DATASTORE_SQL_URL = "https://data.ca.gov/api/3/action/datastore_search_sql"
CEDEN_DATASTORE_COLUMNS = [
    "StationName",
    "StationCode",
    "SampleDate",
    "CollectionTime",
    "MethodName",
    "Analyte",
    "Unit",
    "Result",
    "ResultSub",
    "DataSource",
    "TargetLatitude",
    "TargetLongitude",
    "SampleComments",
    "CollectionComments",
    "ResultsComments",
    "SampleID",
    "SampleDateTime",
]


def _clean_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "not recorded", "nr"}:
        return None
    return text


def _safe_float(value: Any) -> float | None:
    text = _clean_text(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _canonical_parameter(value: Any) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    normalized = re.sub(r"[^a-z]", "", text.lower())
    if any(term in normalized for term in ENTEROCOCCUS_TERMS):
        return "enterococcus"
    return None


def _normalized_token(value: Any) -> str:
    cleaned = _clean_text(value) or ""
    return re.sub(r"[^a-z0-9]+", "", cleaned.lower())


def _normalize_method_or_unit(value: Any) -> str:
    return _normalized_token(value)


def _parse_sample_datetime(sample_datetime: Any, sample_date: Any, collection_time: Any) -> datetime | None:
    timestamp = _clean_text(sample_datetime)
    if timestamp:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(timestamp, fmt)
            except ValueError:
                continue

    date_text = _clean_text(sample_date)
    if date_text is None:
        return None
    time_text = _clean_text(collection_time)
    if time_text and " " in time_text:
        time_text = time_text.split(" ", 1)[1]
    time_text = time_text or "00:00:00"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(f"{date_text} {time_text}", fmt)
        except ValueError:
            continue
    return None


def _county_from_station_name(station_name: Any) -> str | None:
    text = _clean_text(station_name)
    if text is None or "," not in text:
        return None
    county = text.rsplit(",", 1)[-1].strip()
    return county or None


def load_ceden_csv(path: Path, nrows: int | None = None) -> pd.DataFrame:
    return pd.read_csv(
        path,
        dtype=str,
        encoding="utf-8-sig",
        low_memory=False,
        nrows=nrows,
        on_bad_lines="skip",
    )


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def build_ceden_datastore_sql(
    resource_id: str,
    station_codes: list[str],
    limit: int,
    offset: int = 0,
) -> str:
    cleaned_codes = sorted({_clean_text(code) for code in station_codes if _clean_text(code)})
    if not cleaned_codes:
        raise ValueError("station_codes must contain at least one non-empty code")

    code_chunks = [cleaned_codes[index : index + 100] for index in range(0, len(cleaned_codes), 100)]
    code_clauses = []
    for chunk in code_chunks:
        values = ", ".join(f"'{_sql_literal(code)}'" for code in chunk)
        code_clauses.append(f"\"StationCode\" IN ({values})")
    station_filter = "(" + " OR ".join(code_clauses) + ")"
    selected_columns = ", ".join(f"\"{column}\"" for column in CEDEN_DATASTORE_COLUMNS)
    return (
        f"SELECT {selected_columns} FROM \"{resource_id}\" "
        f"WHERE LOWER(\"Analyte\") = 'enterococcus' AND {station_filter} "
        f"ORDER BY \"SampleDateTime\" DESC LIMIT {limit} OFFSET {offset}"
    )


_STATION_BATCH_SIZE = 80  # keep URL well under server 414 limit (~8 KB)


def fetch_ceden_datastore_subset(
    resource_id: str,
    station_codes: list[str],
    max_rows: int | None = None,
    batch_size: int = 5000,
    cache_path: Path | None = None,
    client: httpx.Client | Any | None = None,
) -> pd.DataFrame:
    if max_rows is not None and max_rows <= 0:
        return pd.DataFrame(columns=CEDEN_DATASTORE_COLUMNS)

    cleaned_codes = sorted({_clean_text(c) for c in station_codes if _clean_text(c)})
    station_batches = [
        cleaned_codes[i : i + _STATION_BATCH_SIZE]
        for i in range(0, len(cleaned_codes), _STATION_BATCH_SIZE)
    ]

    owns_client = client is None
    client = client or httpx.Client(timeout=60.0, follow_redirects=True)
    frames: list[pd.DataFrame] = []
    try:
        for stn_batch in station_batches:
            offset = 0
            batch_frames = 0
            while True:
                limit = batch_size if max_rows is None else min(batch_size, max_rows - batch_frames * batch_size)
                if limit <= 0:
                    break
                sql = build_ceden_datastore_sql(
                    resource_id=resource_id,
                    station_codes=stn_batch,
                    limit=limit,
                    offset=offset,
                )
                response = client.get(CEDEN_DATASTORE_SQL_URL, params={"sql": sql}, timeout=60.0)
                response.raise_for_status()
                records = response.json().get("result", {}).get("records", [])
                if not records:
                    break
                frame = pd.DataFrame(records)
                frames.append(frame)
                offset += len(frame)
                batch_frames += 1
                if len(frame) < limit:
                    break
    finally:
        if owns_client:
            client.close()

    subset = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=CEDEN_DATASTORE_COLUMNS)
    # Dedup across station batches on (StationCode, SampleDateTime)
    dedup_cols = [c for c in ("StationCode", "SampleDateTime") if c in subset.columns]
    if dedup_cols:
        subset = subset.drop_duplicates(subset=dedup_cols, keep="last").reset_index(drop=True)
    if cache_path is not None and not subset.empty:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        subset.to_csv(cache_path, index=False)
    return subset


def normalize_ceden_sites(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    sites = frame.copy()
    sites["station_code"] = sites["StationCode"].map(_clean_text)
    sites["station_name"] = sites["StationName"].map(_clean_text)
    sites["county"] = sites["station_name"].map(_county_from_station_name)
    sites["latitude"] = sites["TargetLatitude"].map(_safe_float)
    sites["longitude"] = sites["TargetLongitude"].map(_safe_float)
    sites["station_code_token"] = sites["station_code"].map(_normalized_token)
    sites["station_name_token"] = sites["station_name"].map(_normalized_token)
    return (
        sites[
            [
                "station_code",
                "station_name",
                "county",
                "latitude",
                "longitude",
                "station_code_token",
                "station_name_token",
            ]
        ]
        .dropna(subset=["station_code"])
        .drop_duplicates(subset=["station_code"])
        .reset_index(drop=True)
    )


def normalize_ceden_results(frame: pd.DataFrame, stv_threshold: float) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    results = frame.copy()
    results["analyte"] = results["Analyte"].map(_canonical_parameter)
    results = results.loc[results["analyte"] == "enterococcus"].copy()
    if results.empty:
        return pd.DataFrame()

    results["station_code"] = results["StationCode"].map(_clean_text)
    results["station_name"] = results["StationName"].map(_clean_text)
    results["county"] = results["station_name"].map(_county_from_station_name)
    results["sample_time"] = [
        _parse_sample_datetime(sample_datetime, sample_date, collection_time)
        for sample_datetime, sample_date, collection_time in zip(
            results.get("SampleDateTime", pd.Series(index=results.index)),
            results.get("SampleDate", pd.Series(index=results.index)),
            results.get("CollectionTime", pd.Series(index=results.index)),
            strict=False,
        )
    ]
    results["sample_time"] = pd.to_datetime(results["sample_time"], errors="coerce")
    results["sample_date"] = results["sample_time"].dt.date
    result_sub = pd.to_numeric(results.get("ResultSub"), errors="coerce")
    raw_result = pd.to_numeric(results.get("Result"), errors="coerce")
    results["value"] = result_sub.where(result_sub.notna(), raw_result)
    # Enterococcus is a non-negative count (MPN/CFU/copies). Negative results are
    # invalid sentinels (e.g. -999/-1000 "not analyzed") — drop them so they don't
    # poison the lag/rolling features or the label. Mirrors the guard in
    # beachwatch.normalize_beachwatch_results. The .dropna(subset=[...,"value"])
    # below then removes these rows.
    results.loc[results["value"] < 0, "value"] = np.nan
    results["method"] = results["MethodName"].fillna("unknown").astype(str).str.strip()
    results["units"] = results["Unit"].fillna("unknown").astype(str).str.strip()
    # Method-aware: PCR (copies) judged against the molecular threshold, not the
    # culture STV. See app.data.pipeline.exceedance.
    # Source correction before the predicate reads them: a culture method
    # cannot report copies (see units_corrections), and is_pcr_measurement
    # would otherwise judge such a row against 1413 instead of 104.
    results["units"] = correct_units_series(results["method"], results["units"])
    results["exceeds_stv"] = compute_exceeds_stv(
        results["value"], results["method"], results["units"], stv_threshold
    )
    results["data_source"] = (
        results["DataSource"].map(_clean_text).fillna("SafeToSwim").map(lambda value: f"{value}.SafeToSwim")
    )
    results["latitude"] = results["TargetLatitude"].map(_safe_float)
    results["longitude"] = results["TargetLongitude"].map(_safe_float)
    results["sample_comments"] = results.get("SampleComments", pd.Series(index=results.index)).map(_clean_text)
    results["collection_comments"] = results.get(
        "CollectionComments", pd.Series(index=results.index)
    ).map(_clean_text)
    results["results_comments"] = results.get("ResultsComments", pd.Series(index=results.index)).map(_clean_text)
    results["sample_id"] = results.get("SampleID", pd.Series(index=results.index)).map(_clean_text)
    return (
        results[
            [
                "station_code",
                "station_name",
                "county",
                "sample_time",
                "sample_date",
                "analyte",
                "method",
                "units",
                "value",
                "exceeds_stv",
                "data_source",
                "latitude",
                "longitude",
                "sample_comments",
                "collection_comments",
                "results_comments",
                "sample_id",
            ]
        ]
        .dropna(subset=["station_code", "sample_time", "value"])
        .sort_values(["station_code", "sample_time"])
        .reset_index(drop=True)
    )


def _build_site_fallback(results: pd.DataFrame) -> pd.DataFrame:
    if results.empty:
        return pd.DataFrame()
    fallback = (
        results.sort_values("sample_time")
        .groupby("station_code", as_index=False)
        .tail(1)
        .loc[:, ["station_code", "station_name", "county", "latitude", "longitude"]]
        .copy()
    )
    fallback["station_code_token"] = fallback["station_code"].map(_normalized_token)
    fallback["station_name_token"] = fallback["station_name"].map(_normalized_token)
    return fallback.reset_index(drop=True)


def build_ceden_station_crosswalk(
    ceden_sites: pd.DataFrame,
    beachwatch_stations: pd.DataFrame,
    max_distance_km: float = 0.5,
) -> pd.DataFrame:
    if ceden_sites.empty or beachwatch_stations.empty:
        return pd.DataFrame()

    station_candidates = beachwatch_stations.copy()
    station_candidates["name_token"] = station_candidates["name"].map(_normalized_token)
    station_candidates["county_clean"] = station_candidates["county"].map(_clean_text)

    exact_code = station_candidates.drop_duplicates(subset=["name_token"]).set_index("name_token")
    assignments: list[dict[str, Any]] = []
    for _, row in ceden_sites.iterrows():
        code_token = row.get("station_code_token")
        name_token = row.get("station_name_token")
        match = None
        match_method = None
        if code_token and code_token in exact_code.index:
            match = exact_code.loc[code_token]
            match_method = "station_code"
        elif name_token and name_token in exact_code.index:
            match = exact_code.loc[name_token]
            match_method = "station_name"
        else:
            county = _clean_text(row.get("county"))
            lat = _safe_float(row.get("latitude"))
            lon = _safe_float(row.get("longitude"))
            if county and lat is not None and lon is not None:
                county_candidates = station_candidates.loc[
                    (station_candidates["county_clean"] == county)
                    & station_candidates["latitude"].notna()
                    & station_candidates["longitude"].notna()
                ]
                best = None
                for _, candidate in county_candidates.iterrows():
                    distance_km = haversine_km(
                        lat,
                        lon,
                        float(candidate["latitude"]),
                        float(candidate["longitude"]),
                    )
                    if best is None or distance_km < best["distance_km"]:
                        best = {
                            "candidate": candidate,
                            "distance_km": distance_km,
                        }
                if best is not None and best["distance_km"] <= max_distance_km:
                    match = best["candidate"]
                    match_method = "nearest_same_county"

        if match is None:
            continue

        assignments.append(
            {
                "station_code": row["station_code"],
                "beach_id": match["beach_id"],
                "match_method": match_method,
            }
        )

    return pd.DataFrame(assignments).drop_duplicates(subset=["station_code"]).reset_index(drop=True)


def merge_ceden_into_beachwatch_bundle(
    stations: pd.DataFrame,
    observations: pd.DataFrame,
    advisories: pd.DataFrame,
    ceden_results_raw: pd.DataFrame,
    ceden_sites_raw: pd.DataFrame,
    stv_threshold: float,
) -> dict[str, pd.DataFrame]:
    if observations.empty:
        return {
            "stations": stations,
            "observations": observations,
            "advisories": advisories,
            "beach_day": build_beach_day_frame(observations, stations, advisories),
            "ceden_crosswalk": pd.DataFrame(),
            "ceden_observations": pd.DataFrame(),
        }

    ceden_results = normalize_ceden_results(ceden_results_raw, stv_threshold)
    if ceden_results.empty:
        return {
            "stations": stations,
            "observations": observations,
            "advisories": advisories,
            "beach_day": build_beach_day_frame(observations, stations, advisories),
            "ceden_crosswalk": pd.DataFrame(),
            "ceden_observations": pd.DataFrame(),
        }

    ceden_sites = normalize_ceden_sites(ceden_sites_raw)
    if ceden_sites.empty:
        ceden_sites = _build_site_fallback(ceden_results)

    crosswalk = build_ceden_station_crosswalk(ceden_sites, stations)
    if crosswalk.empty:
        return {
            "stations": stations,
            "observations": observations,
            "advisories": advisories,
            "beach_day": build_beach_day_frame(observations, stations, advisories),
            "ceden_crosswalk": crosswalk,
            "ceden_observations": pd.DataFrame(),
        }

    mapped = ceden_results.merge(crosswalk, on="station_code", how="inner")
    station_lookup = stations[["beach_id", "name", "county", "usepa_id"]].rename(
        columns={"name": "station_name_bw", "county": "county_bw"}
    )
    mapped = mapped.merge(station_lookup, on="beach_id", how="left")
    mapped["county"] = mapped["county_bw"].fillna(mapped["county"])
    mapped["station_name"] = mapped["station_name_bw"].fillna(mapped["station_name"])
    mapped["beach_name"] = mapped["station_name"]
    mapped["weather"] = None
    mapped["storm_drain_flow"] = None
    mapped["tidal_height"] = None
    mapped["surf_height_observed"] = None
    mapped["turbidity_observed"] = None
    mapped["odor"] = None
    mapped["water_color"] = None

    existing = observations.copy()
    if "data_source" not in existing.columns:
        existing["data_source"] = "BeachWatch"

    mapped_observations = mapped[
        [
            "beach_id",
            "sample_time",
            "sample_date",
            "analyte",
            "method",
            "units",
            "value",
            "exceeds_stv",
            "county",
            "station_name",
            "beach_name",
            "usepa_id",
            "weather",
            "storm_drain_flow",
            "tidal_height",
            "surf_height_observed",
            "turbidity_observed",
            "odor",
            "water_color",
            "data_source",
            "station_code",
        ]
    ].copy()

    combined = pd.concat([existing, mapped_observations], ignore_index=True, sort=False)
    source_priority = {
        "BeachWatch": 0,
        "BeachWatch.SafeToSwim": 1,
        "CEDEN.SafeToSwim": 2,
        "Central Valley Water Board.SafeToSwim": 3,
    }
    combined["_source_priority"] = combined["data_source"].map(source_priority).fillna(9)
    combined["_value_key"] = pd.to_numeric(combined["value"], errors="coerce").round(6)
    combined["_method_key"] = combined["method"].map(_normalize_method_or_unit)
    combined["_unit_key"] = combined["units"].map(_normalize_method_or_unit)
    combined["_sample_time_key"] = pd.to_datetime(combined["sample_time"], errors="coerce")
    combined = (
        combined.sort_values(["_source_priority", "_sample_time_key"])
        .drop_duplicates(
            subset=[
                "beach_id",
                "_sample_time_key",
                "analyte",
                "data_source",
                "_method_key",
                "_unit_key",
                "_value_key",
            ],
            keep="first",
        )
    )
    mirror_source_counts = (
        combined.groupby(["beach_id", "_sample_time_key", "analyte", "_value_key"])["data_source"]
        .transform("nunique")
        .fillna(0)
    )
    mirrored = combined.loc[mirror_source_counts.gt(1)].copy()
    non_mirrored = combined.loc[~mirror_source_counts.gt(1)].copy()
    mirrored = mirrored.drop_duplicates(
        subset=["beach_id", "_sample_time_key", "analyte", "_value_key"],
        keep="first",
    )
    combined = (
        pd.concat([non_mirrored, mirrored], ignore_index=True, sort=False)
        .drop(columns=["_source_priority", "_value_key", "_method_key", "_unit_key", "_sample_time_key"])
        .reset_index(drop=True)
    )

    latest_samples = combined.groupby("beach_id")["sample_time"].max().rename("latest_official_sample_at")
    stations_updated = stations.drop(columns=["latest_official_sample_at"], errors="ignore").merge(
        latest_samples,
        on="beach_id",
        how="left",
    )

    return {
        "stations": stations_updated,
        "observations": combined,
        "advisories": advisories,
        "beach_day": build_beach_day_frame(combined, stations_updated, advisories),
        "ceden_crosswalk": crosswalk,
        "ceden_observations": mapped_observations,
    }
