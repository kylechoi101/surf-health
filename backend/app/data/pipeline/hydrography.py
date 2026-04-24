from __future__ import annotations

import asyncio
import logging

import httpx
import pandas as pd

from app.data.pipeline.external_covariates import haversine_km

logger = logging.getLogger(__name__)


async def _fetch_huc12(client: httpx.AsyncClient, lat: float, lon: float) -> str | None:
    url = (
        "https://watersgeo.epa.gov/arcgis/rest/services"
        "/NHDPlus_NP21/WBD_NP21_Simplified/MapServer/0/query"
    )
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "HUC_12",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        r = await client.get(url, params=params, timeout=15.0)
        r.raise_for_status()
        payload = r.json()
        if payload.get("features"):
            return payload["features"][0]["attributes"].get("HUC_12")
    except Exception as exc:
        logger.warning("HUC12 lookup failed for (%.4f, %.4f): %s", lat, lon, exc)
    return None


async def _fetch_nearest_usgs_gage(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
    radius_km: float = 50.0,
) -> dict | None:
    """
    Query USGS NWIS site service for the nearest stream-discharge gage (parameterCd=00060)
    using a bounding-box search.
    """
    deg = radius_km / 111.0
    params = {
        "format": "rdb",
        "bBox": f"{lon - deg:.4f},{lat - deg:.4f},{lon + deg:.4f},{lat + deg:.4f}",
        "siteType": "ST",
        "parameterCd": "00060",
        "siteOutput": "basic",
        "hasDataTypeCd": "iv",
    }
    try:
        r = await client.get(
            "https://waterservices.usgs.gov/nwis/site/", params=params, timeout=20.0
        )
        r.raise_for_status()
        # RDB format: comment lines start with #, first non-comment line = headers,
        # second = type format, data starts at line index 2.
        lines = [ln for ln in r.text.splitlines() if not ln.startswith("#") and ln.strip()]
        if len(lines) < 3:
            return None
        headers = lines[0].split("\t")
        try:
            site_no_idx = headers.index("site_no")
            lat_idx = headers.index("dec_lat_va")
            lon_idx = headers.index("dec_long_va")
        except ValueError:
            return None
        nearest: dict | None = None
        min_dist = float("inf")
        for line in lines[2:]:
            parts = line.split("\t")
            try:
                gage_id = parts[site_no_idx].strip()
                gage_lat = float(parts[lat_idx])
                gage_lon = float(parts[lon_idx])
            except (IndexError, ValueError):
                continue
            if not gage_id:
                continue
            d = haversine_km(lat, lon, gage_lat, gage_lon)
            if d < min_dist:
                min_dist = d
                nearest = {"gage_id": gage_id, "distance_km": d}
        return nearest
    except Exception as exc:
        logger.warning("USGS gage lookup failed for (%.4f, %.4f): %s", lat, lon, exc)
    return None


async def _resolve_beach_link(client: httpx.AsyncClient, row: pd.Series) -> dict:
    lat = row.get("latitude")
    lon = row.get("longitude")
    beach_id = row.get("beach_id")

    if pd.isna(lat) or pd.isna(lon):
        return {
            "beach_id": beach_id,
            "hydrologic_unit_id": None,
            "pour_point_id": None,
            "pour_point_latitude": None,
            "pour_point_longitude": None,
            "distance_to_pour_point_km": None,
            "nearest_stream_gage_id": None,
            "distance_to_gage_km": None,
            "watershed_area_km2": None,
            "mapping_confidence": "none",
        }

    huc12, gage_result = await asyncio.gather(
        _fetch_huc12(client, float(lat), float(lon)),
        _fetch_nearest_usgs_gage(client, float(lat), float(lon)),
    )

    if huc12 and gage_result:
        confidence = "high"
    elif huc12:
        confidence = "medium"
    else:
        confidence = "none"

    return {
        "beach_id": beach_id,
        "hydrologic_unit_id": huc12,
        "pour_point_id": f"pp_{huc12}" if huc12 else None,
        # Coastal beach: the beach coordinate is the coastal outlet
        "pour_point_latitude": float(lat),
        "pour_point_longitude": float(lon),
        "distance_to_pour_point_km": 0.0,
        "nearest_stream_gage_id": gage_result["gage_id"] if gage_result else None,
        "distance_to_gage_km": gage_result["distance_km"] if gage_result else None,
        # watershed_area_km2 requires NHDPlus geodata; left None until that source is added
        "watershed_area_km2": None,
        "mapping_confidence": confidence,
    }


async def _build_links_async(
    beach_metadata: pd.DataFrame, concurrency: int = 10
) -> pd.DataFrame:
    if beach_metadata.empty:
        return pd.DataFrame()

    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(client: httpx.AsyncClient, row: pd.Series) -> dict:
        async with semaphore:
            return await _resolve_beach_link(client, row)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [_bounded(client, row) for _, row in beach_metadata.iterrows()]
        links = await asyncio.gather(*tasks)

    return pd.DataFrame(list(links))


def build_hydrologic_beach_links(
    beach_metadata: pd.DataFrame, limit: int | None = None
) -> pd.DataFrame:
    """
    Map each beach to its coastal HUC12, pour point, and nearest USGS stream-discharge gage.

    Uses EPA WATERS for HUC12 and USGS NWIS site service for gage assignment.
    Runs concurrent requests up to concurrency=10 to avoid hammering the APIs.
    """
    if limit is not None:
        beach_metadata = beach_metadata.head(limit)
    return asyncio.run(_build_links_async(beach_metadata))
