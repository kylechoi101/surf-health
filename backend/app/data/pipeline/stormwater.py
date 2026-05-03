from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd


INCH_TO_MM = 25.4
RAIN_MONITORING_PAUSE_INCHES = 0.1
RAIN_GENERAL_ADVISORY_INCHES = 0.2

STORMWATER_NUMERIC_COLUMNS = [
    "nearest_stormwater_asset_km",
    "nearest_stormwater_outfall_km",
    "nearest_tmdl_stormwater_site_km",
    "stormwater_asset_count_0_5km",
    "stormwater_asset_count_1km",
    "stormwater_asset_count_2km",
    "stormwater_outfall_count_1km",
    "stormwater_outfall_count_2km",
    "stormwater_tmdl_site_count_2km",
    "stormwater_low_flow_diversion_count_2km",
    "stormwater_field_verified_count_2km",
    "stormwater_impaired_water_count_2km",
    "rain_72h_inches",
    "rain_72h_monitoring_pause_flag",
    "rain_72h_general_advisory_flag",
]

STORMWATER_SOURCE_LAYERS = [
    {
        "slug": "san_diego_drain_structure",
        "source_name": "City of San Diego Drain Structure",
        "city": "San Diego",
        "layer_url": "https://webmaps.sandiego.gov/arcgis/rest/services/StormWater/SWD_Public/MapServer/2",
        "asset_type": "drain_structure",
    },
    {
        "slug": "san_diego_drain_conveyance",
        "source_name": "City of San Diego Drain Conveyance",
        "city": "San Diego",
        "layer_url": "https://webmaps.sandiego.gov/arcgis/rest/services/StormWater/SWD_Public/MapServer/6",
        "asset_type": "drain_conveyance",
    },
    {
        "slug": "orange_county_outfalls",
        "source_name": "OC Public Works MS4 Outfall Locations",
        "city": "Orange County",
        "layer_url": "https://ocgis.com/arcpub/rest/services/Environmental_Resources/Outfall_Inspections/FeatureServer/0",
        "asset_type": "outfall",
    },
    {
        "slug": "santa_monica_discharge_points",
        "source_name": "City of Santa Monica Storm Drain Discharge Points",
        "city": "Santa Monica",
        "layer_url": "https://gis.santamonica.gov/server/rest/services/Storm_Drain_Network_2023/FeatureServer/22",
        "asset_type": "discharge_point",
    },
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _first_present(row: pd.Series, candidates: tuple[str, ...]) -> Any:
    for candidate in candidates:
        for column in row.index:
            if str(column).lower() != candidate.lower():
                continue
            value = row.get(column)
            if value is not None and not pd.isna(value) and str(value).strip() != "":
                return value
    return None


def _truthy_flag(value: Any) -> int:
    text = _clean_text(value).lower()
    if not text:
        return 0
    if text in {"1", "true", "t", "y", "yes"}:
        return 1
    if any(token in text for token in ("yes", "divert", "verified", "active", "present")):
        return 1
    return 0


def _geometry_to_lon_lat(value: Any) -> tuple[float | None, float | None]:
    if not isinstance(value, dict):
        return None, None
    if "x" in value and "y" in value:
        return _safe_float(value.get("x")), _safe_float(value.get("y"))
    geom_type = value.get("type")
    coordinates = value.get("coordinates")
    if geom_type == "Point" and isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
        return _safe_float(coordinates[0]), _safe_float(coordinates[1])
    flattened: list[tuple[float, float]] = []

    def collect(coords: Any) -> None:
        if (
            isinstance(coords, (list, tuple))
            and len(coords) >= 2
            and isinstance(coords[0], (int, float))
            and isinstance(coords[1], (int, float))
        ):
            flattened.append((float(coords[0]), float(coords[1])))
        elif isinstance(coords, (list, tuple)):
            for item in coords:
                collect(item)

    collect(coordinates)
    if not flattened:
        return None, None
    lon = sum(point[0] for point in flattened) / len(flattened)
    lat = sum(point[1] for point in flattened) / len(flattened)
    return lon, lat


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        output = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(output):
        return None
    return output


def _infer_asset_type(row: pd.Series, source_name: str, default_asset_type: str) -> str:
    explicit = _first_present(row, ("asset_type", "AssetType", "TYPE", "SUBTYPE", "STRUCTURETYPE"))
    text = " ".join(
        _clean_text(value)
        for value in (
            explicit,
            source_name,
            _first_present(row, ("FACILITYID", "NAME", "HUNAME", "StationName")),
        )
    ).lower()
    if "outfall" in text:
        return "outfall"
    if "discharge" in text:
        return "discharge_point"
    if "receiving" in text or " rw" in text or text.endswith("-rw"):
        return "tmdl_receiving_water"
    return _clean_text(explicit) or default_asset_type


def records_from_geojson(payload: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for feature in payload.get("features", []):
        props = dict(feature.get("properties") or {})
        props["geometry"] = feature.get("geometry")
        rows.append(props)
    return pd.DataFrame(rows)


def normalize_stormwater_assets(
    raw_assets: pd.DataFrame,
    *,
    source_name: str,
    default_city: str | None = None,
    default_asset_type: str = "outfall",
) -> pd.DataFrame:
    columns = [
        "asset_id",
        "source_name",
        "asset_type",
        "city",
        "county",
        "receiving_water",
        "latitude",
        "longitude",
        "low_flow_diversion_flag",
        "field_verified_flag",
        "tmdl_bacteria_flag",
        "impaired_water_flag",
    ]
    if raw_assets.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for _, row in raw_assets.iterrows():
        lon, lat = _geometry_to_lon_lat(row.get("geometry"))
        lat = _safe_float(_first_present(row, ("latitude", "lat", "TargetLatitude", "Y"))) if lat is None else lat
        lon = _safe_float(_first_present(row, ("longitude", "lon", "TargetLongitude", "X"))) if lon is None else lon
        if lat is None or lon is None:
            continue
        asset_id = _first_present(
            row,
            ("asset_id", "FACILITYID", "GlobalID", "StationCode", "NAME", "HUNAME", "OBJECTID", "FID"),
        )
        if asset_id is None:
            asset_id = f"{source_name}:{len(rows)}"
        inspected = _first_present(row, ("INSPECTED", "SHAY_DATA", "VERIFIED", "field_verified"))
        low_flow = _first_present(
            row,
            (
                "LOW_FLOW_DIVERSION",
                "low_flow_diversion",
                "LFD",
                "DIVERSION",
                "LOWFLOW",
                "LOWFLOWDIVERSION",
            ),
        )
        tmdl_text = " ".join(
            _clean_text(_first_present(row, (column,)))
            for column in ("Program", "ParentProject", "Project", "StationName", "asset_type")
        ).lower()
        rows.append(
            {
                "asset_id": _clean_text(asset_id),
                "source_name": source_name,
                "asset_type": _infer_asset_type(row, source_name, default_asset_type),
                "city": _clean_text(_first_present(row, ("city", "CITY", "CITY_CODE"))) or default_city,
                "county": _clean_text(_first_present(row, ("county", "County", "COUNTY"))),
                "receiving_water": _clean_text(
                    _first_present(row, ("receiving_water", "OF_CREEK", "WaterbodyName", "StationName"))
                ),
                "latitude": lat,
                "longitude": lon,
                "low_flow_diversion_flag": _truthy_flag(low_flow),
                "field_verified_flag": _truthy_flag(inspected),
                "tmdl_bacteria_flag": int("tmdl" in tmdl_text and "bacteria" in tmdl_text),
                "impaired_water_flag": int("303" in tmdl_text or "impaired" in tmdl_text),
            }
        )

    output = pd.DataFrame(rows, columns=columns)
    if output.empty:
        return output
    return output.drop_duplicates(subset=["source_name", "asset_id"]).reset_index(drop=True)


def derive_tmdl_assets_from_ceden(ceden_results: pd.DataFrame) -> pd.DataFrame:
    if ceden_results.empty:
        return normalize_stormwater_assets(pd.DataFrame(), source_name="CEDEN TMDL")

    df = ceden_results.copy()
    text_columns = [
        column
        for column in ("Program", "ParentProject", "Project", "StationName", "SampleComments", "CollectionComments")
        if column in df.columns
    ]
    combined = df[text_columns].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
    analyte = df.get("Analyte", pd.Series("", index=df.index)).fillna("").astype(str).str.lower()
    mask = combined.str.contains("tmdl|wqip|project clean water|outfall|receiving water|storm drain|runoff", regex=True)
    mask &= analyte.str.contains("enterococcus|e\\. coli|fecal|coliform|bacteria", regex=True)
    df = df.loc[mask].copy()
    if df.empty:
        return normalize_stormwater_assets(pd.DataFrame(), source_name="CEDEN TMDL")

    df["latitude"] = pd.to_numeric(df.get("TargetLatitude"), errors="coerce")
    df["longitude"] = pd.to_numeric(df.get("TargetLongitude"), errors="coerce")
    df = df.dropna(subset=["latitude", "longitude", "StationCode"])
    grouped = (
        df.groupby(["StationCode", "StationName", "latitude", "longitude"], dropna=False)
        .size()
        .reset_index(name="tmdl_sample_count")
    )
    grouped["asset_type"] = grouped["StationName"].fillna("").str.lower().map(
        lambda text: "tmdl_outfall"
        if any(token in text for token in ("outfall", "storm drain", "-sd", " sd"))
        else "tmdl_receiving_water"
    )
    grouped["Program"] = "Total Maximum Daily Load Bacteria"
    return normalize_stormwater_assets(
        grouped,
        source_name="CEDEN TMDL / WQIP receiving-water and outfall stations",
        default_asset_type="tmdl_receiving_water",
    )


def build_beach_stormwater_features(
    beaches: pd.DataFrame,
    stormwater_assets: pd.DataFrame,
    *,
    max_distance_km: float = 10.0,
) -> pd.DataFrame:
    output_columns = ["beach_id", *STORMWATER_NUMERIC_COLUMNS[:-3]]
    if beaches.empty:
        return pd.DataFrame(columns=output_columns)

    assets = stormwater_assets.copy()
    if not assets.empty:
        assets["latitude"] = pd.to_numeric(assets["latitude"], errors="coerce")
        assets["longitude"] = pd.to_numeric(assets["longitude"], errors="coerce")
        assets = assets.dropna(subset=["latitude", "longitude"])

    rows: list[dict[str, Any]] = []
    for _, beach in beaches.iterrows():
        beach_id = beach.get("beach_id")
        lat = _safe_float(beach.get("latitude"))
        lon = _safe_float(beach.get("longitude"))
        base = {
            "beach_id": beach_id,
            "nearest_stormwater_asset_km": math.nan,
            "nearest_stormwater_outfall_km": math.nan,
            "nearest_tmdl_stormwater_site_km": math.nan,
            "stormwater_asset_count_0_5km": 0,
            "stormwater_asset_count_1km": 0,
            "stormwater_asset_count_2km": 0,
            "stormwater_outfall_count_1km": 0,
            "stormwater_outfall_count_2km": 0,
            "stormwater_tmdl_site_count_2km": 0,
            "stormwater_low_flow_diversion_count_2km": 0,
            "stormwater_field_verified_count_2km": 0,
            "stormwater_impaired_water_count_2km": 0,
        }
        if lat is None or lon is None or assets.empty:
            rows.append(base)
            continue

        lat_delta = max_distance_km / 111.0
        lon_delta = max_distance_km / (111.0 * max(math.cos(math.radians(lat)), 0.2))
        candidates = assets.loc[
            assets["latitude"].between(lat - lat_delta, lat + lat_delta)
            & assets["longitude"].between(lon - lon_delta, lon + lon_delta)
        ].copy()
        if candidates.empty:
            rows.append(base)
            continue

        distances = candidates.apply(
            lambda row: haversine_km(lat, lon, float(row["latitude"]), float(row["longitude"])),
            axis=1,
        )
        nearby = candidates.assign(distance_km=distances).loc[distances <= max_distance_km].copy()
        if nearby.empty:
            rows.append(base)
            continue

        outfall_mask = nearby["asset_type"].astype(str).str.contains("outfall|discharge", case=False, na=False)
        tmdl_mask = nearby["asset_type"].astype(str).str.contains("tmdl", case=False, na=False) | (
            pd.to_numeric(nearby.get("tmdl_bacteria_flag", 0), errors="coerce").fillna(0) > 0
        )
        within_2 = nearby["distance_km"] <= 2.0
        base.update(
            {
                "nearest_stormwater_asset_km": float(nearby["distance_km"].min()),
                "nearest_stormwater_outfall_km": (
                    float(nearby.loc[outfall_mask, "distance_km"].min()) if outfall_mask.any() else math.nan
                ),
                "nearest_tmdl_stormwater_site_km": (
                    float(nearby.loc[tmdl_mask, "distance_km"].min()) if tmdl_mask.any() else math.nan
                ),
                "stormwater_asset_count_0_5km": int((nearby["distance_km"] <= 0.5).sum()),
                "stormwater_asset_count_1km": int((nearby["distance_km"] <= 1.0).sum()),
                "stormwater_asset_count_2km": int(within_2.sum()),
                "stormwater_outfall_count_1km": int((outfall_mask & (nearby["distance_km"] <= 1.0)).sum()),
                "stormwater_outfall_count_2km": int((outfall_mask & within_2).sum()),
                "stormwater_tmdl_site_count_2km": int((tmdl_mask & within_2).sum()),
                "stormwater_low_flow_diversion_count_2km": int(
                    pd.to_numeric(nearby.loc[within_2, "low_flow_diversion_flag"], errors="coerce").fillna(0).sum()
                ),
                "stormwater_field_verified_count_2km": int(
                    pd.to_numeric(nearby.loc[within_2, "field_verified_flag"], errors="coerce").fillna(0).sum()
                ),
                "stormwater_impaired_water_count_2km": int(
                    pd.to_numeric(nearby.loc[within_2, "impaired_water_flag"], errors="coerce").fillna(0).sum()
                ),
            }
        )
        rows.append(base)
    return pd.DataFrame(rows, columns=output_columns)


def add_rain_policy_features(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    precip_72h = pd.to_numeric(output.get("precip_mm_72h"), errors="coerce")
    rain_inches = precip_72h / INCH_TO_MM
    output["rain_72h_inches"] = rain_inches
    output["rain_72h_monitoring_pause_flag"] = (
        precip_72h >= (RAIN_MONITORING_PAUSE_INCHES * INCH_TO_MM)
    ).fillna(False).astype(int)
    output["rain_72h_general_advisory_flag"] = (
        precip_72h >= (RAIN_GENERAL_ADVISORY_INCHES * INCH_TO_MM)
    ).fillna(False).astype(int)
    return output


def apply_stormwater_features(
    beach_day: pd.DataFrame,
    stormwater_features: pd.DataFrame,
) -> pd.DataFrame:
    output = beach_day.copy()
    existing = [column for column in STORMWATER_NUMERIC_COLUMNS if column in output.columns]
    if existing:
        output = output.drop(columns=existing)
    if not stormwater_features.empty:
        output = output.merge(stormwater_features, on="beach_id", how="left")
    for column in STORMWATER_NUMERIC_COLUMNS:
        if column not in output.columns:
            output[column] = math.nan
    count_columns = [column for column in STORMWATER_NUMERIC_COLUMNS if column.endswith("_count_2km") or column.endswith("_count_1km") or column.endswith("_count_0_5km") or column.endswith("_flag")]
    output[count_columns] = output[count_columns].fillna(0)
    return add_rain_policy_features(output)


def _fetch_with_retry(url: str, max_retries: int = 3, base_delay: float = 2.0, timeout: int = 120) -> bytes:
    """Fetch URL with exponential backoff on timeouts/errors."""
    for attempt in range(max_retries):
        try:
            with urlopen(url, timeout=timeout) as response:
                return response.read()
        except (TimeoutError, URLError) as e:
            if attempt == max_retries - 1:
                print(f"[stormwater] Failed to fetch {url} after {max_retries} attempts: {e}", flush=True)
                raise
            delay = base_delay * (2 ** attempt)
            print(f"[stormwater] Fetch error ({e}). Retrying in {delay}s...", flush=True)
            time.sleep(delay)
    raise RuntimeError("Unreachable")


def _arcgis_query_url(layer_url: str, offset: int, page_size: int) -> str:
    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        "resultOffset": offset,
        "resultRecordCount": page_size,
    }
    return f"{layer_url.rstrip('/')}/query?{urlencode(params)}"


def _arcgis_count_url(layer_url: str) -> str:
    params = {"where": "1=1", "returnCountOnly": "true", "f": "json"}
    return f"{layer_url.rstrip('/')}/query?{urlencode(params)}"


def _fetch_arcgis_count(layer_url: str) -> int | None:
    data = _fetch_with_retry(_arcgis_count_url(layer_url))
    payload = json.loads(data.decode("utf-8"))
    count = payload.get("count")
    return int(count) if count is not None else None


def fetch_arcgis_geojson(layer_url: str, *, page_size: int = 1000, max_pages: int = 250) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    expected_count = _fetch_arcgis_count(layer_url)
    for page in range(max_pages):
        url = _arcgis_query_url(layer_url, page * page_size, page_size)
        data = _fetch_with_retry(url)
        payload = json.loads(data.decode("utf-8"))
        page_features = payload.get("features", [])
        features.extend(page_features)
        if expected_count is not None and len(features) >= expected_count:
            break
        if len(page_features) < page_size:
            break
    return {"type": "FeatureCollection", "features": features}


def download_stormwater_sources(raw_dir: Path) -> list[Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    manifest: list[dict[str, Any]] = []
    for source in STORMWATER_SOURCE_LAYERS:
        print(f"[stormwater] downloading {source['slug']}", flush=True)
        payload = fetch_arcgis_geojson(source["layer_url"])
        path = raw_dir / f"{source['slug']}.geojson"
        path.write_text(json.dumps(payload))
        paths.append(path)
        manifest.append({**source, "local_path": str(path), "feature_count": len(payload.get("features", []))})
        print(f"[stormwater] {source['slug']}: {len(payload.get('features', []))} features", flush=True)
    (raw_dir / "source_manifest.json").write_text(json.dumps(manifest, indent=2))
    return paths


def load_stormwater_assets(raw_dir: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    manifest_path = raw_dir / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    for source in manifest:
        path = Path(source["local_path"])
        if not path.exists():
            continue
        raw = records_from_geojson(json.loads(path.read_text()))
        frames.append(
            normalize_stormwater_assets(
                raw,
                source_name=source["source_name"],
                default_city=source.get("city"),
                default_asset_type=source.get("asset_type", "outfall"),
            )
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build stormwater/outfall features for curated beaches.")
    parser.add_argument("--curated-dir", type=Path, default=Path("data/curated"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/stormwater"))
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--ceden-results-csv", type=Path, default=Path("data/raw/safetoswim_geomeans_2020-present.csv"))
    args = parser.parse_args()

    if args.download:
        download_stormwater_sources(args.raw_dir)
    print("[stormwater] normalizing source assets", flush=True)
    assets = load_stormwater_assets(args.raw_dir)
    if args.ceden_results_csv.exists():
        print("[stormwater] deriving CEDEN TMDL/WQIP assets", flush=True)
        ceden = pd.read_csv(args.ceden_results_csv, dtype=str, low_memory=False, on_bad_lines="skip")
        assets = pd.concat([assets, derive_tmdl_assets_from_ceden(ceden)], ignore_index=True)
    args.curated_dir.mkdir(parents=True, exist_ok=True)
    assets.to_parquet(args.curated_dir / "stormwater_assets.parquet", index=False)

    beaches = pd.read_parquet(args.curated_dir / "beaches.parquet")
    beach_day = pd.read_parquet(args.curated_dir / "beach_day.parquet")
    print("[stormwater] linking assets to beaches", flush=True)
    features = build_beach_stormwater_features(beaches, assets)
    features.to_parquet(args.curated_dir / "stormwater_beach_features.parquet", index=False)
    enriched = apply_stormwater_features(beach_day, features)
    enriched.to_parquet(args.curated_dir / "beach_day.parquet", index=False)
    print(json.dumps({"assets": len(assets), "beaches": len(features), "beach_day_rows": len(enriched)}, indent=2))


if __name__ == "__main__":
    main()
