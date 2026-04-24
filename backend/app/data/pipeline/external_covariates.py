from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from math import atan2, cos, radians, sin, sqrt
from typing import Any

import httpx
import pandas as pd


CDIP_SUMMARY_URL = "https://cdip.ucsd.edu/data_access/sccoos.cdip"
CDIP_JUSTDAR_URL = "https://cdip.ucsd.edu/data_access/justdar.cdip"
EPA_UV_DAILY_URL = "https://data.epa.gov/efservice/getEnvirofactsUVDAILY/ZIP/{zip_code}/JSON"


@dataclass(frozen=True)
class ErddapPointDataset:
    source_name: str
    dataset_url: str
    latitude: float
    longitude: float
    max_distance_km: float = 40.0


ERDDAP_POINT_DATASETS = [
    ErddapPointDataset(
        source_name="cencoos_del_mar_mooring",
        dataset_url=(
            "https://erddap.cencoos.org/erddap/tabledap/del-mar-mooring-1.csv?"
            "time%2Clatitude%2Clongitude%2Cz%2Csea_water_practical_salinity%2Csea_water_temperature"
            "&time%3E={start}T00:00:00Z&time%3C={end}T23:59:59Z"
        ),
        latitude=32.93,
        longitude=-117.32,
        max_distance_km=1500.0,
    ),
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 2 * radius_km * atan2(sqrt(a), sqrt(1 - a))


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _valid_coordinate_pair(latitude: Any, longitude: Any) -> bool:
    lat = _safe_float(latitude)
    lon = _safe_float(longitude)
    return lat is not None and lon is not None


def parse_cdip_summary(text: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("<"):
            continue
        parts = stripped.split("\t")
        if len(parts) < 10:
            continue
        if not parts[1].isdigit():
            continue
        name = parts[2]
        if ", CA" not in name:
            continue
        rows.append(
            {
                "cdip_station_id": parts[1].zfill(3),
                "cdip_station_name": name,
                "latitude": _safe_float(parts[3]),
                "longitude": _safe_float(parts[4]),
                "depth_m": _safe_float(parts[5]),
                "wave_height_m_latest": _safe_float(parts[6]),
                "dominant_period_s_latest": _safe_float(parts[7]),
                "wave_direction_deg_latest": _safe_float(parts[8]),
                "sea_surface_temperature_c_latest": _safe_float(parts[9]),
            }
        )
    return pd.DataFrame(rows).dropna(subset=["latitude", "longitude"]).reset_index(drop=True)


def parse_cdip_pm_text(text: str, station_id: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("<") or not stripped[:4].isdigit():
            continue
        parts = stripped.split()
        if len(parts) < 8:
            continue
        year, month, day, hour, minute = map(int, parts[:5])
        wave_height = _safe_float(parts[5])
        dominant_period = _safe_float(parts[6])
        wave_direction = _safe_float(parts[7])
        if wave_height is None and dominant_period is None and wave_direction is None:
            continue
        rows.append(
            {
                "cdip_station_id": station_id,
                "time": datetime(year, month, day, hour, minute, tzinfo=UTC),
                "wave_height_m": wave_height,
                "dominant_period_s": dominant_period,
                "wave_direction_deg": wave_direction,
            }
        )
    return pd.DataFrame(rows)


def _circular_mean(degrees: pd.Series) -> float | None:
    valid = pd.to_numeric(degrees, errors="coerce").dropna()
    if valid.empty:
        return None
    angles = valid.map(radians)
    sin_mean = angles.map(sin).mean()
    cos_mean = angles.map(cos).mean()
    value = (atan2(sin_mean, cos_mean) * 180.0 / 3.141592653589793) % 360
    return float(value)


def aggregate_cdip_daily(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    enriched = frame.copy()
    enriched["sample_date"] = pd.to_datetime(enriched["time"]).dt.date
    grouped = (
        enriched.groupby(["cdip_station_id", "sample_date"], as_index=False)
        .agg(
            wave_height_m=("wave_height_m", "mean"),
            dominant_period_s=("dominant_period_s", "mean"),
        )
        .reset_index(drop=True)
    )
    direction = (
        enriched.groupby(["cdip_station_id", "sample_date"])["wave_direction_deg"]
        .apply(_circular_mean)
        .rename("wave_direction_deg")
        .reset_index()
    )
    return grouped.merge(direction, on=["cdip_station_id", "sample_date"], how="left")


def _chunk_date_ranges(start: date, end: date, chunk_days: int = 1825) -> list[tuple[date, date]]:
    ranges: list[tuple[date, date]] = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end)
        ranges.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return ranges


async def fetch_cdip_summary(client: httpx.AsyncClient) -> pd.DataFrame:
    response = await client.get(CDIP_SUMMARY_URL, timeout=20.0)
    response.raise_for_status()
    return parse_cdip_summary(response.text)


async def fetch_cdip_daily_covariates(
    client: httpx.AsyncClient,
    station_id: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for chunk_start, chunk_end in _chunk_date_ranges(start, end):
        url = f"{CDIP_JUSTDAR_URL}?{station_id}+pm+{chunk_start:%Y%m%d}+{chunk_end:%Y%m%d}"
        response = await client.get(url, timeout=45.0)
        response.raise_for_status()
        parsed = parse_cdip_pm_text(response.text, station_id)
        if not parsed.empty:
            frames.append(parsed)
    if not frames:
        return pd.DataFrame()
    return aggregate_cdip_daily(pd.concat(frames, ignore_index=True))


def assign_nearest_cdip_station(
    stations: pd.DataFrame,
    cdip_summary: pd.DataFrame,
    max_distance_km: float = 150.0,
) -> pd.DataFrame:
    assignments: list[dict[str, Any]] = []
    for _, row in stations.iterrows():
        if not _valid_coordinate_pair(row.get("latitude"), row.get("longitude")):
            continue
        best: dict[str, Any] | None = None
        for _, station in cdip_summary.iterrows():
            distance_km = haversine_km(
                float(row["latitude"]),
                float(row["longitude"]),
                float(station["latitude"]),
                float(station["longitude"]),
            )
            if best is None or distance_km < best["cdip_distance_km"]:
                best = {
                    "beach_id": row["beach_id"],
                    "cdip_station_id": station["cdip_station_id"],
                    "cdip_station_name": station["cdip_station_name"],
                    "cdip_distance_km": distance_km,
                }
        if best and best["cdip_distance_km"] <= max_distance_km:
            assignments.append(best)
    return pd.DataFrame(assignments)


async def fetch_epa_uv_daily(
    client: httpx.AsyncClient,
    zip_codes: list[str],
) -> pd.DataFrame:
    async def _fetch_one(zip_code: str) -> dict[str, Any] | None:
        response = await client.get(EPA_UV_DAILY_URL.format(zip_code=zip_code), timeout=15.0)
        response.raise_for_status()
        payload = response.json()
        if not payload:
            return None
        row = payload[0]
        uv_date = datetime.strptime(row["DATE"], "%b/%d/%Y").date()
        return {
            "zip_code": zip_code,
            "uv_index": _safe_float(row.get("UV_INDEX")),
            "uv_alert": row.get("UV_ALERT"),
            "forecast_date": uv_date.isoformat(),
        }

    results = await asyncio.gather(*[_fetch_one(zip_code) for zip_code in zip_codes], return_exceptions=True)
    rows = [item for item in results if isinstance(item, dict)]
    return pd.DataFrame(rows)


async def fetch_erddap_daily_covariates(
    client: httpx.AsyncClient,
    dataset: ErddapPointDataset,
    start: date,
    end: date,
) -> pd.DataFrame:
    url = dataset.dataset_url.format(start=start.isoformat(), end=end.isoformat())
    response = await client.get(url, timeout=30.0)
    response.raise_for_status()
    if response.text.startswith("Error"):
        return pd.DataFrame()
    frame = pd.read_csv(StringIO(response.text), skiprows=[1])
    if frame.empty:
        return pd.DataFrame()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce", utc=True)
    frame["z"] = pd.to_numeric(frame["z"], errors="coerce")
    frame["sea_water_practical_salinity"] = pd.to_numeric(
        frame["sea_water_practical_salinity"], errors="coerce"
    )
    frame["sea_water_temperature"] = pd.to_numeric(frame["sea_water_temperature"], errors="coerce")
    per_time = frame.sort_values(["time", "z"], ascending=[True, False]).groupby("time", as_index=False).first()
    per_time["sample_date"] = per_time["time"].dt.date
    daily = (
        per_time.groupby("sample_date", as_index=False)
        .agg(
            salinity_psu=("sea_water_practical_salinity", "mean"),
            water_temperature_c=("sea_water_temperature", "mean"),
        )
        .assign(source_name=dataset.source_name)
    )
    return daily


def assign_nearest_erddap_source(stations: pd.DataFrame) -> pd.DataFrame:
    assignments: list[dict[str, Any]] = []
    for _, row in stations.iterrows():
        if not _valid_coordinate_pair(row.get("latitude"), row.get("longitude")):
            continue
        best: dict[str, Any] | None = None
        for dataset in ERDDAP_POINT_DATASETS:
            distance_km = haversine_km(
                float(row["latitude"]),
                float(row["longitude"]),
                dataset.latitude,
                dataset.longitude,
            )
            if best is None or distance_km < best["erddap_distance_km"]:
                best = {
                    "beach_id": row["beach_id"],
                    "erddap_source_name": dataset.source_name,
                    "erddap_distance_km": distance_km,
                }
        if best is not None:
            dataset = next(item for item in ERDDAP_POINT_DATASETS if item.source_name == best["erddap_source_name"])
            if best["erddap_distance_km"] <= dataset.max_distance_km:
                assignments.append(best)
    return pd.DataFrame(assignments)


async def enrich_beach_day_with_external_covariates(
    stations: pd.DataFrame,
    beach_day: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if beach_day.empty:
        return stations, beach_day, pd.DataFrame()

    start_date = pd.to_datetime(beach_day["sample_date"]).dt.date.min()
    end_date = pd.to_datetime(beach_day["sample_date"]).dt.date.max()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        cdip_summary = await fetch_cdip_summary(client)
        cdip_assignments = assign_nearest_cdip_station(stations, cdip_summary)
        if not cdip_assignments.empty:
            stations = stations.merge(cdip_assignments, on="beach_id", how="left")
            beach_day = beach_day.merge(
                cdip_assignments[["beach_id", "cdip_station_id", "cdip_distance_km"]],
                on="beach_id",
                how="left",
            )
            cdip_ranges = (
                beach_day.dropna(subset=["cdip_station_id"])
                .groupby("cdip_station_id")["sample_date"]
                .agg(["min", "max"])
                .reset_index()
            )
            frames: list[pd.DataFrame] = []
            for _, row in cdip_ranges.iterrows():
                frames.append(
                    await fetch_cdip_daily_covariates(
                        client,
                        str(row["cdip_station_id"]),
                        pd.to_datetime(row["min"]).date(),
                        pd.to_datetime(row["max"]).date(),
                    )
                )
            cdip_daily = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True) if frames else pd.DataFrame()
            if not cdip_daily.empty:
                beach_day = beach_day.merge(
                    cdip_daily,
                    on=["cdip_station_id", "sample_date"],
                    how="left",
                )

        erddap_assignments = assign_nearest_erddap_source(stations)
        if not erddap_assignments.empty:
            stations = stations.merge(erddap_assignments, on="beach_id", how="left")
            beach_day = beach_day.merge(
                erddap_assignments[["beach_id", "erddap_source_name", "erddap_distance_km"]],
                on="beach_id",
                how="left",
            )
            frames = []
            for dataset in ERDDAP_POINT_DATASETS:
                if dataset.source_name not in set(erddap_assignments["erddap_source_name"]):
                    continue
                frames.append(await fetch_erddap_daily_covariates(client, dataset, start_date, end_date))
            erddap_daily = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True) if frames else pd.DataFrame()
            if not erddap_daily.empty:
                beach_day = beach_day.merge(
                    erddap_daily,
                    left_on=["erddap_source_name", "sample_date"],
                    right_on=["source_name", "sample_date"],
                    how="left",
                ).drop(columns=["source_name"], errors="ignore")

        zip_codes = sorted(
            {
                str(zip_code).zfill(5)
                for zip_code in stations.get("zip_code", pd.Series(dtype=str)).dropna().tolist()
                if str(zip_code).strip().isdigit()
            }
        )
        uv_daily = await fetch_epa_uv_daily(client, zip_codes) if zip_codes else pd.DataFrame()

    return stations, beach_day, uv_daily
