from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from math import atan2, cos, radians, sin
from typing import Any

import httpx
import pandas as pd

log = logging.getLogger(__name__)

# Covariate columns that MUST be present (non-all-null) after a successful CDIP
# enrichment.  If any is entirely missing we raise so the pipeline fails loudly
# rather than silently producing NaN-only columns that collapse the calibrator.
CDIP_REQUIRED_COVARIATE_COLUMNS: tuple[str, ...] = (
    "wave_height_m",
    "dominant_period_s",
)


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


def concat_non_empty(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate frames, tolerating a list where every frame is empty.

    A full upstream outage (e.g. ERDDAP 500s on every dataset) yields a
    non-empty list of empty frames; ``pd.concat`` on the filtered list would
    raise ``ValueError: No objects to concatenate``.
    """
    non_empty = [frame for frame in frames if not frame.empty]
    return pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()


# Re-exported from app.core.geo, which is now the single definition. Kept
# importable here because seven modules already import it from this path.
from app.core.geo import haversine_km  # noqa: E402,F401


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
    if not rows:
        # Return a typed empty frame so callers never hit dropna KeyError
        return pd.DataFrame(
            columns=[
                "cdip_station_id", "cdip_station_name",
                "latitude", "longitude", "depth_m",
                "wave_height_m_latest", "dominant_period_s_latest",
                "wave_direction_deg_latest", "sea_surface_temperature_c_latest",
            ]
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
    enriched["sample_date"] = pd.to_datetime(enriched["time"]).dt.tz_convert(None).dt.normalize()
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
    """Fetch the CDIP station summary.  Returns empty DataFrame on any network
    or HTTP error so callers can proceed with zero CDIP coverage rather than
    crashing the entire enrichment pipeline."""
    try:
        response = await client.get(CDIP_SUMMARY_URL, timeout=20.0)
        response.raise_for_status()
        df = parse_cdip_summary(response.text)
        if df.empty:
            log.warning(
                "[cdip] sccoos summary returned 0 CA stations — "
                "check %s for upstream changes", CDIP_SUMMARY_URL
            )
        else:
            log.info("[cdip] summary: %d CA stations loaded", len(df))
        return df
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "[cdip] fetch_cdip_summary failed (%s: %s) — "
            "wave covariates will be NaN for this run",
            type(exc).__name__, exc,
        )
        return pd.DataFrame(
            columns=[
                "cdip_station_id", "cdip_station_name",
                "latitude", "longitude", "depth_m",
                "wave_height_m_latest", "dominant_period_s_latest",
                "wave_direction_deg_latest", "sea_surface_temperature_c_latest",
            ]
        )


async def fetch_cdip_daily_covariates(
    client: httpx.AsyncClient,
    station_id: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Fetch JUSTDAR PM timeseries for one station.  Returns empty DataFrame on
    any network/HTTP error so a single bad station does not abort the pipeline."""
    frames: list[pd.DataFrame] = []
    for chunk_start, chunk_end in _chunk_date_ranges(start, end):
        url = f"{CDIP_JUSTDAR_URL}?{station_id}+pm+{chunk_start:%Y%m%d}+{chunk_end:%Y%m%d}"
        try:
            response = await client.get(url, timeout=45.0)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "[cdip] station %s chunk %s–%s fetch failed (%s: %s) — skipping chunk",
                station_id, chunk_start, chunk_end, type(exc).__name__, exc,
            )
            continue
        parsed = parse_cdip_pm_text(response.text, station_id)
        if not parsed.empty:
            frames.append(parsed)
        else:
            log.debug(
                "[cdip] station %s chunk %s–%s returned 0 parseable rows",
                station_id, chunk_start, chunk_end,
            )
    if not frames:
        log.warning(
            "[cdip] station %s: no data returned across all requested chunks "
            "(%s – %s)", station_id, start, end
        )
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
    """Fetch ERDDAP daily covariates.  Returns empty DataFrame on network/HTTP
    error so one failing dataset does not abort the enrichment pipeline."""
    url = dataset.dataset_url.format(start=start.isoformat(), end=end.isoformat())
    try:
        response = await client.get(url, timeout=30.0)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "[erddap] fetch failed for %s (%s: %s) — skipping",
            dataset.source_name, type(exc).__name__, exc,
        )
        return pd.DataFrame()
    if response.text.startswith("Error"):
        log.warning("[erddap] %s returned error text — skipping", dataset.source_name)
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
    per_time["sample_date"] = per_time["time"].dt.tz_convert(None).dt.normalize()
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


def assert_covariate_columns_populated(
    beach_day: pd.DataFrame,
    cdip_assignments: pd.DataFrame,
    required_columns: tuple[str, ...] = CDIP_REQUIRED_COVARIATE_COLUMNS,
) -> None:
    """Fail loudly if a named covariate column is all-null after the CDIP merge.

    A silent all-null column downstream causes the calibrator to produce
    degenerate p_exceed=1.00 mass (no wave signal → all beaches read as
    extreme), which was the immediate trigger for the sanity-guard clamp.
    Better to crash the pipeline here and fix the upstream feed.

    Only runs when CDIP station assignments were non-empty (i.e. we expected
    to receive data).  If the summary fetch itself returned 0 stations the
    assertion is skipped — that failure is already logged as a warning.
    """
    if cdip_assignments.empty:
        return
    assigned_beaches = set(cdip_assignments["beach_id"])
    rows_with_station = beach_day.loc[
        beach_day.get("beach_id", pd.Series(dtype=str)).isin(assigned_beaches)
    ]
    if rows_with_station.empty:
        return
    missing_cols: list[str] = []
    for col in required_columns:
        if col not in beach_day.columns or rows_with_station[col].isna().all():
            missing_cols.append(col)
    if missing_cols:
        raise RuntimeError(
            f"[cdip] COVARIATE ASSERTION FAILED — the following columns are "
            f"entirely null after CDIP merge for {len(assigned_beaches)} assigned beaches: "
            f"{missing_cols}.  "
            f"This means the CDIP JUSTDAR fetch returned no data.  "
            f"Check network connectivity to {CDIP_JUSTDAR_URL} and re-run "
            f"--normalize-beachwatch --with-external-covariates once the feed recovers."
        )
    log.info(
        "[cdip] covariate assertion passed — %s all have non-null values "
        "across %d assigned-beach rows",
        required_columns, len(rows_with_station),
    )


async def enrich_beach_day_with_external_covariates(
    stations: pd.DataFrame,
    beach_day: pd.DataFrame,
    assert_covariates: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Enrich beach_day with CDIP wave, ERDDAP oceanographic, and EPA UV data.

    Args:
        stations: Station metadata DataFrame.
        beach_day: Beach-day observation frame.
        assert_covariates: If True, raise RuntimeError when CDIP wave columns
            are all-null after merge despite non-empty station assignments.
            Set this to True when running the normalisation pipeline so silent
            CDIP drops fail the build rather than propagating NaN into the
            calibrator.  Defaults to False for backwards compatibility.
    """
    if beach_day.empty:
        return stations, beach_day, pd.DataFrame()

    start_date = pd.to_datetime(beach_day["sample_date"]).dt.date.min()
    end_date = pd.to_datetime(beach_day["sample_date"]).dt.date.max()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        cdip_summary = await fetch_cdip_summary(client)
        cdip_assignments = assign_nearest_cdip_station(stations, cdip_summary)
        if not cdip_assignments.empty:
            _cdip_cols = [c for c in cdip_assignments.columns if c != "beach_id"]
            stations = stations.drop(columns=[c for c in _cdip_cols if c in stations.columns])
            stations = stations.merge(cdip_assignments, on="beach_id", how="left")
            _cdip_merge_cols = ["cdip_station_id", "cdip_distance_km"]
            beach_day = beach_day.drop(columns=[c for c in _cdip_merge_cols if c in beach_day.columns])
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
            cdip_daily = concat_non_empty(frames)
            if not cdip_daily.empty:
                beach_day = beach_day.merge(
                    cdip_daily,
                    on=["cdip_station_id", "sample_date"],
                    how="left",
                )
                log.info(
                    "[cdip] merged %d station-day rows onto beach_day "
                    "(wave_height_m non-null: %d / %d)",
                    len(cdip_daily),
                    beach_day["wave_height_m"].notna().sum() if "wave_height_m" in beach_day.columns else 0,
                    len(beach_day),
                )
            else:
                log.warning(
                    "[cdip] ALL station fetches returned empty — "
                    "wave_height_m will be NaN for this run.  "
                    "Feed URL: %s", CDIP_JUSTDAR_URL
                )

            if assert_covariates:
                assert_covariate_columns_populated(beach_day, cdip_assignments)
        else:
            log.info("[cdip] no station assignments — CDIP covariates skipped")

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
            erddap_daily = concat_non_empty(frames)
            if erddap_daily.empty:
                log.warning(
                    "[erddap] ALL dataset fetches returned empty — "
                    "ERDDAP covariates will be NaN for this run."
                )
            else:
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
