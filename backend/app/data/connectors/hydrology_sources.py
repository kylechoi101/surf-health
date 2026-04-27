from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_USGS_MISSING_VALUES = {"-999999", ""}
_USGS_IV_MAX_DAYS = 90  # NWIS IV returns ReadTimeout for multi-site requests > ~90 days


@dataclass
class UsgsNwisConnector:
    chunk_size: int = 100  # NWIS site limit per request

    async def fetch_streamflow(
        self, gage_ids: list[str], start: date, end: date
    ) -> pd.DataFrame:
        if not gage_ids:
            return pd.DataFrame()

        settings = get_settings()
        settings.hydrology_cache_dir.mkdir(parents=True, exist_ok=True)

        gage_hash = hashlib.md5(",".join(sorted(gage_ids)).encode()).hexdigest()
        cache_file = (
            settings.hydrology_cache_dir
            / f"usgs_iv_{gage_hash}_{start.isoformat()}_{end.isoformat()}.parquet"
        )
        if cache_file.exists():
            return pd.read_parquet(cache_file)

        # Chunk by both site count and time window — NWIS IV times out on long multi-site ranges
        site_chunks = [
            gage_ids[i : i + self.chunk_size]
            for i in range(0, len(gage_ids), self.chunk_size)
        ]
        time_windows = _date_windows(start, end, _USGS_IV_MAX_DAYS)

        all_rows: list[dict] = []
        async with httpx.AsyncClient(follow_redirects=True) as client:
            for site_chunk in site_chunks:
                for window_start, window_end in time_windows:
                    rows = await self._fetch_chunk(
                        client, site_chunk, window_start, window_end, settings
                    )
                    all_rows.extend(rows)

        df = pd.DataFrame(all_rows)
        if not df.empty:
            df.to_parquet(cache_file, index=False)
        else:
            logger.warning(
                "USGS streamflow fetch returned no rows for %d gages [%s, %s]",
                len(gage_ids), start, end,
            )
        return df

    async def _fetch_chunk(
        self,
        client: httpx.AsyncClient,
        gage_ids: list[str],
        start: date,
        end: date,
        settings,
    ) -> list[dict]:
        params = {
            "format": "json",
            "sites": ",".join(gage_ids),
            "startDT": start.isoformat(),
            "endDT": end.isoformat(),
            "parameterCd": "00060",  # Discharge, cubic feet per second
        }
        try:
            response = await client.get(
                f"{settings.usgs_nwis_base_url}/iv/", params=params, timeout=60.0
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "USGS NWIS returned HTTP %s for chunk %s [%s, %s]",
                exc.response.status_code, gage_ids[:3], start, end,
            )
            return []
        except Exception as exc:
            logger.error(
                "USGS NWIS fetch failed for chunk %s [%s, %s]: %s",
                gage_ids[:3], start, end, type(exc).__name__,
            )
            return []

        rows: list[dict] = []
        for ts in payload.get("value", {}).get("timeSeries", []):
            gage_id = ts["sourceInfo"]["siteCode"][0]["value"]
            for val in ts["values"][0]["value"]:
                raw = val.get("value", "")
                # Map missing/sentinel values to NaN rather than 0
                discharge = np.nan if raw in _USGS_MISSING_VALUES else float(raw)
                qualifiers = val.get("qualifiers", [])
                provisional = "P" in qualifiers
                rows.append({
                    "gage_id": gage_id,
                    "time_utc": val["dateTime"],
                    "discharge_cfs": discharge,
                    "gage_height_ft": np.nan,
                    "provisional": provisional,
                    "source_name": "usgs_nwis",
                })
        return rows


def _date_windows(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    windows = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=max_days - 1), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


@dataclass
class CnrfcObservedPrecipConnector:
    """
    Fetches observed precipitation from the NOAA NWS Observations API.

    Limitation: NWS observations typically cover ~7 days of history.
    For historical training data, provide pre-downloaded CSVs via --cnrfc-observed-csv.
    """

    async def fetch_observed_precip(
        self, station_ids: list[str], start: date, end: date
    ) -> pd.DataFrame:
        if not station_ids:
            return pd.DataFrame()

        settings = get_settings()
        settings.precip_cache_dir.mkdir(parents=True, exist_ok=True)

        station_hash = hashlib.md5(",".join(sorted(station_ids)).encode()).hexdigest()
        cache_file = (
            settings.precip_cache_dir
            / f"noaa_nws_{station_hash}_{start.isoformat()}_{end.isoformat()}.parquet"
        )
        if cache_file.exists():
            return pd.read_parquet(cache_file)

        rows: list[dict] = []
        async with httpx.AsyncClient() as client:
            tasks = [self._fetch_station(client, sid, start, end) for sid in station_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for station_id, result in zip(station_ids, results):
            if isinstance(result, Exception):
                logger.warning("NWS precip fetch failed for %s: %s", station_id, result)
                continue
            rows.extend(result)

        df = pd.DataFrame(rows)
        if not df.empty:
            df.to_parquet(cache_file, index=False)
        else:
            logger.warning(
                "NWS precip fetch returned no rows for %d stations [%s, %s]",
                len(station_ids), start, end,
            )
        return df

    async def _fetch_station(
        self,
        client: httpx.AsyncClient,
        station_id: str,
        start: date,
        end: date,
    ) -> list[dict]:
        url = f"https://api.weather.gov/stations/{station_id}/observations"
        params = {
            "start": f"{start.isoformat()}T00:00:00Z",
            "end": f"{end.isoformat()}T23:59:59Z",
        }
        response = await client.get(url, params=params, timeout=15.0)
        response.raise_for_status()
        data = response.json()

        rows: list[dict] = []
        for feature in data.get("features", []):
            props = feature["properties"]
            coords = feature.get("geometry", {}).get("coordinates", [np.nan, np.nan])
            precip_data = props.get("precipitationLastHour") or {}
            raw_precip = precip_data.get("value")
            unit = precip_data.get("unitCode", "")

            if raw_precip is None:
                precip_mm = np.nan
            elif "wmoUnit:m" in unit:
                precip_mm = float(raw_precip) * 1000.0
            else:
                precip_mm = float(raw_precip)

            rows.append({
                "station_id": station_id,
                "time_utc": props.get("timestamp"),
                "precip_mm_increment": precip_mm,
                "latitude": coords[1] if len(coords) > 1 else np.nan,
                "longitude": coords[0] if coords else np.nan,
                "elevation_m": (props.get("elevation") or {}).get("value", np.nan),
                "source_name": "noaa_nws",
            })
        return rows


@dataclass
class OpenMeteoHistoricalPrecipConnector:
    """
    Fetches hourly historical precipitation from the Open-Meteo archive API.

    No API key required. Backed by ERA5-Land reanalysis (~9 km, 1940-present).
    Suitable for historical training data where NWS observations don't reach far enough back.
    Cache is keyed by rounded coordinates (0.1°) + date range.
    """

    BASE_URL: str = "https://archive-api.open-meteo.com/v1/archive"
    concurrency: int = 5

    async def _fetch_coord(
        self,
        client: httpx.AsyncClient,
        lat: float,
        lon: float,
        start: date,
        end: date,
        cache_dir: Path,
    ) -> pd.DataFrame:
        lat_r = round(lat, 1)
        lon_r = round(lon, 1)
        cache_key = f"openmeteo_{lat_r}_{lon_r}_{start.isoformat()}_{end.isoformat()}.parquet"
        cache_file = cache_dir / cache_key
        if cache_file.exists():
            return pd.read_parquet(cache_file)

        params = {
            "latitude": lat_r,
            "longitude": lon_r,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": "precipitation",
            "timezone": "UTC",
            "precipitation_unit": "mm",
        }
        try:
            r = await client.get(self.BASE_URL, params=params, timeout=60.0)
            r.raise_for_status()
            payload = r.json()
        except Exception as exc:
            logger.error("Open-Meteo fetch failed for (%.1f, %.1f): %s", lat_r, lon_r, exc)
            return pd.DataFrame()

        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        precip_vals = hourly.get("precipitation", [])
        if not times:
            return pd.DataFrame()

        station_id = f"{lat_r}_{lon_r}"
        df = pd.DataFrame({
            "station_id": station_id,
            "time_utc": pd.to_datetime(times, utc=True),
            "precip_mm_increment": [float(p) if p is not None else np.nan for p in precip_vals],
            "latitude": lat_r,
            "longitude": lon_r,
            "elevation_m": float(payload.get("elevation", np.nan)),
            "source_name": "open_meteo",
        })
        df.to_parquet(cache_file, index=False)
        return df

    async def fetch_historical_precip(
        self,
        locations: list[tuple[float, float]],
        start: date,
        end: date,
        cache_dir: Path,
    ) -> pd.DataFrame:
        if not locations:
            return pd.DataFrame()

        cache_dir.mkdir(parents=True, exist_ok=True)
        # Deduplicate by rounded coordinate to avoid redundant requests
        unique_coords = list({(round(lat, 1), round(lon, 1)) for lat, lon in locations})

        semaphore = asyncio.Semaphore(self.concurrency)

        async def _bounded(client: httpx.AsyncClient, lat: float, lon: float) -> pd.DataFrame:
            async with semaphore:
                return await self._fetch_coord(client, lat, lon, start, end, cache_dir)

        async with httpx.AsyncClient() as client:
            tasks = [_bounded(client, lat, lon) for lat, lon in unique_coords]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        frames = []
        for (lat, lon), result in zip(unique_coords, results):
            if isinstance(result, Exception):
                logger.error("Open-Meteo gather failed for (%.1f, %.1f): %s", lat, lon, result)
            elif isinstance(result, pd.DataFrame) and not result.empty:
                frames.append(result)

        if not frames:
            logger.warning("Open-Meteo returned no data for %d locations [%s, %s]", len(locations), start, end)
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)


@dataclass
class OpenMeteoHistoricalSolarWindConnector:
    """
    Fetches hourly historical UV / cloud-cover / shortwave radiation / wind from
    the Open-Meteo archive API. Same source (ERA5-Land, ~9 km grid) as the precip
    connector. No API key required.

    Variables fetched per (rounded coord, date range):
      cloud_cover            — % (0–100, total column)
      shortwave_radiation    — W/m² hourly (proxy for UV at the surface)
      uv_index               — Open-Meteo modeled UV index (1–11 scale)
      wind_speed_10m         — m/s
      wind_direction_10m     — degrees (meteorological convention: where wind is FROM)

    Rationale: enterococci T₉₀ under full sun is ~1–2 hours; under overcast it
    can be 24+ hours. Onshore vs offshore wind compresses or disperses runoff
    plumes against the shoreline. These features capture the dominant
    decay and transport terms not present in precip+wave alone.
    """

    BASE_URL: str = "https://archive-api.open-meteo.com/v1/archive"
    concurrency: int = 5
    HOURLY_VARS: tuple[str, ...] = (
        "cloud_cover",
        "shortwave_radiation",
        "uv_index",
        "wind_speed_10m",
        "wind_direction_10m",
    )

    async def _fetch_coord(
        self,
        client: httpx.AsyncClient,
        lat: float,
        lon: float,
        start: date,
        end: date,
        cache_dir: Path,
    ) -> pd.DataFrame:
        lat_r = round(lat, 1)
        lon_r = round(lon, 1)
        cache_key = f"openmeteo_solwind_{lat_r}_{lon_r}_{start.isoformat()}_{end.isoformat()}.parquet"
        cache_file = cache_dir / cache_key
        if cache_file.exists():
            return pd.read_parquet(cache_file)

        params = {
            "latitude": lat_r,
            "longitude": lon_r,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(self.HOURLY_VARS),
            "timezone": "UTC",
            "wind_speed_unit": "ms",
        }
        try:
            r = await client.get(self.BASE_URL, params=params, timeout=60.0)
            r.raise_for_status()
            payload = r.json()
        except Exception as exc:
            logger.error("Open-Meteo solar/wind fetch failed for (%.1f, %.1f): %s", lat_r, lon_r, exc)
            return pd.DataFrame()

        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        if not times:
            return pd.DataFrame()

        station_id = f"{lat_r}_{lon_r}"
        df = pd.DataFrame({
            "station_id": station_id,
            "time_utc": pd.to_datetime(times, utc=True),
            "latitude": lat_r,
            "longitude": lon_r,
            "source_name": "open_meteo",
        })
        for var in self.HOURLY_VARS:
            vals = hourly.get(var, [])
            df[var] = [float(v) if v is not None else np.nan for v in vals]
        df.to_parquet(cache_file, index=False)
        return df

    async def fetch_historical_solar_wind(
        self,
        locations: list[tuple[float, float]],
        start: date,
        end: date,
        cache_dir: Path,
    ) -> pd.DataFrame:
        if not locations:
            return pd.DataFrame()
        cache_dir.mkdir(parents=True, exist_ok=True)
        unique_coords = list({(round(lat, 1), round(lon, 1)) for lat, lon in locations})

        semaphore = asyncio.Semaphore(self.concurrency)

        async def _bounded(client: httpx.AsyncClient, lat: float, lon: float) -> pd.DataFrame:
            async with semaphore:
                return await self._fetch_coord(client, lat, lon, start, end, cache_dir)

        async with httpx.AsyncClient() as client:
            tasks = [_bounded(client, lat, lon) for lat, lon in unique_coords]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        frames: list[pd.DataFrame] = []
        for (lat, lon), result in zip(unique_coords, results):
            if isinstance(result, Exception):
                logger.error("Open-Meteo solar/wind gather failed for (%.1f, %.1f): %s", lat, lon, result)
            elif isinstance(result, pd.DataFrame) and not result.empty:
                frames.append(result)

        if not frames:
            logger.warning("Open-Meteo solar/wind returned no data for %d locations [%s, %s]", len(locations), start, end)
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)


@dataclass
class CnrfcQpfConnector:
    """Stub for CNRFC QPF (gridded forecast precipitation). Deferred to Phase 2."""

    async def fetch_qpf(self, start: date, end: date) -> pd.DataFrame:
        return pd.DataFrame(columns=[
            "grid_id", "forecast_issue_time_utc", "valid_start_utc",
            "valid_end_utc", "qpf_mm", "latitude", "longitude",
        ])


@dataclass
class NhdPlusMetadataConnector:
    data_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.data_dir is None:
            self.data_dir = get_settings().nhdplus_data_dir
