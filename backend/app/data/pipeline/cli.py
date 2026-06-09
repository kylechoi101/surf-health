from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Callable

import pandas as pd
import httpx

from app.core.config import get_settings
from app.data.connectors.base import SourceContext
from app.data.connectors.official_sources import (
    CEDEN_FIB_RESULTS_2010_2020_URL,
    CEDEN_FIB_RESULTS_2010_2020_RESOURCE_ID,
    CEDEN_FIB_RESULTS_2020_PRESENT_URL,
    CEDEN_FIB_RESULTS_2020_PRESENT_RESOURCE_ID,
    CEDEN_FIB_RESULTS_BEFORE_2010_URL,
    CEDEN_FIB_RESULTS_BEFORE_2010_RESOURCE_ID,
    CEDEN_FIB_SITES_FILENAME,
    CEDEN_FIB_SITES_URL,
    default_connectors,
)
from app.data.pipeline.beachwatch import (
    build_beach_day_frame,
    normalize_advisories,
    normalize_bacteria_results,
    normalize_station_metadata,
    write_curated_bundle,
)
from app.data.pipeline.ceden import (
    fetch_ceden_datastore_subset,
    load_ceden_csv,
    merge_ceden_into_beachwatch_bundle,
)
from app.data.pipeline.curation import curate_beach_days, write_duckdb_snapshot
from app.data.pipeline.external_covariates import enrich_beach_day_with_external_covariates
from app.data.pipeline.station_quality import support_status_for


def _download_file(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
    destination.write_bytes(response.content)
    return destination


def _ceden_results_url_for_path(path: Path | None) -> str:
    name = (path.name.lower() if path is not None else "")
    if "2010-2020" in name:
        return CEDEN_FIB_RESULTS_2010_2020_URL
    if "before-2010" in name or "1969-2010" in name:
        return CEDEN_FIB_RESULTS_BEFORE_2010_URL
    return CEDEN_FIB_RESULTS_2020_PRESENT_URL


def _ceden_results_resource_id_for_path(path: Path | None) -> str:
    name = (path.name.lower() if path is not None else "")
    if "2010-2020" in name:
        return CEDEN_FIB_RESULTS_2010_2020_RESOURCE_ID
    if "before-2010" in name or "1969-2010" in name:
        return CEDEN_FIB_RESULTS_BEFORE_2010_RESOURCE_ID
    return CEDEN_FIB_RESULTS_2020_PRESENT_RESOURCE_ID


def _find_existing_ceden_resource_path(
    requested_path: Path | None,
    raw_dir: Path,
    default_raw_filename: str,
) -> Path | None:
    candidates: list[Path] = []
    if requested_path is not None:
        candidates.append(requested_path)
        candidates.append(raw_dir / requested_path.name)
    candidates.append(raw_dir / default_raw_filename)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _ceden_subset_cache_path(requested_path: Path | None, raw_dir: Path) -> Path:
    if requested_path is not None:
        return requested_path.with_name(f"{requested_path.stem}_enterococcus_subset.csv")
    return raw_dir / "ceden_fib_enterococcus_beachwatch_subset_2020-present.csv"


def _resolve_ceden_resource_path(
    requested_path: Path | None,
    raw_dir: Path,
    default_raw_filename: str,
    resource_url: str,
    downloader: Callable[[str, Path], Path] = _download_file,
) -> Path:
    existing = _find_existing_ceden_resource_path(requested_path, raw_dir, default_raw_filename)
    if existing is not None:
        return existing

    destination = requested_path or (raw_dir / default_raw_filename)
    return downloader(resource_url, destination)


async def ingest_sources() -> dict[str, pd.DataFrame]:
    settings = get_settings()
    data_root = Path(settings.data_dir)
    context = SourceContext(
        raw_dir=data_root / "raw",
        curated_dir=data_root / "curated",
        research_dir=data_root / "research",
    )
    frames: dict[str, pd.DataFrame] = {}
    for connector in default_connectors(
        settings.california_bacteria_dataset_slug,
        settings.california_ceden_fib_dataset_slug,
    ):
        try:
            frames[connector.source_name] = await connector.fetch(context)
        except Exception as exc:
            print(f"[warn] {connector.source_name} fetch failed: {exc}")
            frames[connector.source_name] = pd.DataFrame()
    return frames


def load_beachwatch_csv(path: Path, nrows: int | None = None) -> pd.DataFrame:
    return pd.read_csv(
        path,
        dtype=str,
        encoding="utf-8-sig",
        low_memory=False,
        nrows=nrows,
        on_bad_lines="skip",
    )


def load_beachwatch_results_incremental(path: Path, min_date: pd.Timestamp) -> pd.DataFrame:
    """Read only rows from bw_results.csv with SampleDate >= min_date (chunked, low memory)."""
    frames: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        path,
        dtype=str,
        encoding="utf-8-sig",
        low_memory=False,
        chunksize=50_000,
        on_bad_lines="skip",
    ):
        if "SampleDate" not in chunk.columns:
            frames.append(chunk)
            continue
        dates = pd.to_datetime(chunk["SampleDate"], format="mixed", errors="coerce")
        mask = dates >= min_date
        if mask.any():
            frames.append(chunk[mask])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def normalize_beachwatch_bundle(
    stations_path: Path,
    results_path: Path | None,
    advisories_path: Path,
    max_results_rows: int | None = None,
    results_raw: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    settings = get_settings()
    stations_raw = load_beachwatch_csv(stations_path)
    if results_raw is None:
        results_raw = load_beachwatch_csv(results_path, nrows=max_results_rows)
    advisories_raw = load_beachwatch_csv(advisories_path)

    stations = normalize_station_metadata(stations_raw)
    observations = normalize_bacteria_results(results_raw, settings.epa_marine_enterococcus_stv)
    advisories = normalize_advisories(advisories_raw)

    if not observations.empty and "beach_id" in observations.columns:
        grouped = observations.groupby("beach_id")["sample_time"]
        observation_counts = grouped.size().rename("observation_count")
        # Sampling span (first→last sample) gates out one-time incident stations.
        sampling_span_days = (
            (grouped.max() - grouped.min()).dt.days.rename("sampling_span_days")
        )
        stations = stations.merge(observation_counts, on="beach_id", how="left")
        stations = stations.merge(sampling_span_days, on="beach_id", how="left")
        stations = stations.loc[stations["observation_count"].fillna(0) > 0].copy()
        stations["support_status"] = [
            support_status_for(count, span)
            for count, span in zip(
                stations["observation_count"].fillna(0),
                stations["sampling_span_days"],
                strict=False,
            )
        ]
        stations = stations.drop(columns=["observation_count", "sampling_span_days"])
    else:
        stations["support_status"] = "unsupported"
    advisories = advisories.loc[advisories["beach_id"].isin(stations["beach_id"])].reset_index(drop=True)
    if not observations.empty and "beach_id" in observations.columns:
        observations = observations.loc[observations["beach_id"].isin(stations["beach_id"])].reset_index(drop=True)
    latest_samples = (
        observations.groupby("beach_id")["sample_time"].max().rename("latest_official_sample_at")
        if not observations.empty and "beach_id" in observations.columns
        else pd.Series(dtype="datetime64[ns]", name="latest_official_sample_at")
    )
    if not latest_samples.empty:
        stations = stations.merge(latest_samples, on="beach_id", how="left", suffixes=("", "_new"))
        stations["latest_official_sample_at"] = stations["latest_official_sample_at_new"].fillna(
            stations["latest_official_sample_at"]
        )
        stations = stations.drop(columns=["latest_official_sample_at_new"])

    beach_day = build_beach_day_frame(observations, stations, advisories)
    return {
        "stations": stations,
        "observations": observations,
        "advisories": advisories,
        "beach_day": beach_day,
    }


def build_sample_curated_table() -> pd.DataFrame:
    bacteria_frame = pd.DataFrame(
        [
            {
                "beach_id": "scripps-pier",
                "sample_time": "2026-04-18T08:15:00-07:00",
                "enterococcus_value": 81,
            },
            {
                "beach_id": "manhattan-beach-pier",
                "sample_time": "2026-04-18T08:05:00-07:00",
                "enterococcus_value": 132,
            },
        ]
    )
    covariates = pd.DataFrame(
        [
            {
                "beach_id": "scripps-pier",
                "sample_date": "2026-04-18",
                "wave_height_m": 1.0,
                "dominant_period_s": 10.0,
                "water_temperature_c": 15.5,
                "salinity_psu": 33.6,
                "uv_index": 6.0,
                "wind_speed_mps": 3.8,
            },
            {
                "beach_id": "manhattan-beach-pier",
                "sample_date": "2026-04-18",
                "wave_height_m": 0.7,
                "dominant_period_s": 9.0,
                "water_temperature_c": 16.1,
                "salinity_psu": 32.9,
                "uv_index": 5.0,
                "wind_speed_mps": 4.6,
            },
        ]
    )
    return curate_beach_days(
        bacteria_frame=bacteria_frame,
        covariate_frames=[covariates],
        stv_threshold=get_settings().epa_marine_enterococcus_stv,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Surf Health data pipeline")
    parser.add_argument("--ingest", action="store_true", help="Fetch source metadata from official APIs")
    parser.add_argument(
        "--fixture-curated",
        action="store_true",
        help="Write a sample curated beach_day table to DuckDB for local development",
    )
    parser.add_argument("--normalize-beachwatch", action="store_true")
    parser.add_argument("--stations-csv", type=Path)
    parser.add_argument("--results-csv", type=Path)
    parser.add_argument("--advisories-csv", type=Path)
    parser.add_argument("--max-results-rows", type=int, default=None)
    parser.add_argument("--merge-ceden", action="store_true")
    parser.add_argument("--ceden-results-csv", type=Path)
    parser.add_argument("--ceden-sites-csv", type=Path)
    parser.add_argument("--max-ceden-rows", type=int, default=None)
    parser.add_argument("--force-ceden-fetch", action="store_true", help="Bypass CEDEN cache and fetch fresh data")
    parser.add_argument("--with-external-covariates", action="store_true")
    parser.add_argument("--with-hydrology", action="store_true")
    parser.add_argument(
        "--with-solar-wind",
        action="store_true",
        help="Fetch hourly cloud / shortwave / UV / wind from Open-Meteo and merge "
             "marine-microbiology features (shore_normal_wind, solar_inactivation_index, "
             "days_since_sunny, pier/estuary proximity) into beach_day.",
    )
    parser.add_argument(
        "--with-surf",
        action="store_true",
        help="Fetch the Open-Meteo Marine forecast (waves + primary/secondary swell "
             "trains) for surf-spot beaches and write surf_now.parquet + "
             "surf_daily_forecast.parquet to the curated dir.",
    )
    parser.add_argument(
        "--surf-forecast-days",
        type=int,
        default=7,
        help="Forecast horizon for --with-surf (Open-Meteo marine supports up to 16).",
    )
    parser.add_argument(
        "--with-hourly",
        action="store_true",
        help="Precompute the per-beach hourly forecast+marine series into "
             "hourly_forecast.parquet so the /hourly API route serves from disk "
             "instead of calling Open-Meteo live (which is rate-limited from the "
             "production server, 502-ing all surf data).",
    )
    parser.add_argument("--usgs-gages-csv", type=Path)
    parser.add_argument("--cnrfc-observed-csv", type=Path)
    parser.add_argument("--cnrfc-qpf-csv", type=Path)
    parser.add_argument("--hydrologic-links-csv", type=Path)
    parser.add_argument("--build-hydrologic-links", action="store_true")
    parser.add_argument("--start-date", type=str)
    parser.add_argument("--end-date", type=str)
    args = parser.parse_args()

    if args.ingest:
        frames = asyncio.run(ingest_sources())
        for source, frame in frames.items():
            print(f"{source}: {len(frame)} rows")

    if args.fixture_curated:
        settings = get_settings()
        data_root = Path(settings.data_dir)
        frame = build_sample_curated_table()
        write_duckdb_snapshot(frame, data_root / "research" / "surf_health.duckdb", "beach_day")
        output_path = data_root / "curated" / "beach_day.parquet"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(output_path, index=False)
        print(f"wrote curated beach_day snapshot to {output_path}")

    if args.normalize_beachwatch:
        if not (args.stations_csv and args.results_csv and args.advisories_csv):
            raise SystemExit("--normalize-beachwatch requires --stations-csv, --results-csv, and --advisories-csv")
        settings = get_settings()
        raw_dir = Path(settings.data_dir) / "raw"
        _curated = Path(settings.curated_dir)
        _obs_path = _curated / "observations.parquet"
        _stn_path = _curated / "beaches.parquet"
        _adv_path = _curated / "advisories.parquet"
        _incremental_bw = _obs_path.exists() and _stn_path.exists() and not args.start_date
        if _incremental_bw:
            # Incremental: keep existing stations + observations; only re-normalize new obs + advisories.
            _existing_obs = pd.read_parquet(_obs_path)
            _bw_cutoff = pd.to_datetime(_existing_obs["sample_time"]).max() - pd.Timedelta(days=7)
            print(f"[beachwatch] incremental results fetch from {_bw_cutoff.date()} (existing obs max - 7d)")
            _new_results_raw = load_beachwatch_results_incremental(args.results_csv, _bw_cutoff)
            print(f"[beachwatch] {len(_new_results_raw)} new result rows to normalize")
            _new_obs = normalize_bacteria_results(_new_results_raw, settings.epa_marine_enterococcus_stv) if not _new_results_raw.empty else pd.DataFrame()
            _merged = pd.concat([_existing_obs, _new_obs], ignore_index=True) if not _new_obs.empty else _existing_obs
            _key = [c for c in ("beach_id", "sample_time") if c in _merged.columns]
            _all_obs = _merged.drop_duplicates(subset=_key, keep="last").sort_values(_key).reset_index(drop=True)
            print(f"[beachwatch] merged observations: {len(_all_obs)} rows")
            _advisories_raw = load_beachwatch_csv(args.advisories_csv)
            _all_adv = normalize_advisories(_advisories_raw)
            _all_stn = pd.read_parquet(_stn_path)
            # Drop stale merge-suffix columns (cdip_station_id_x/_y, etc.) — the base
            # columns are authoritative and reseeded each run by enrich_*. Leftover
            # _x/_y from prior partial merges break the next merge.
            _stale = [c for c in _all_stn.columns if c.endswith("_x") or c.endswith("_y")]
            if _stale:
                _all_stn = _all_stn.drop(columns=_stale)
                print(f"[beachwatch] dropped {len(_stale)} stale suffixed columns from stations")
            bundle = {"stations": _all_stn, "observations": _all_obs, "advisories": _all_adv}
        else:
            bundle = normalize_beachwatch_bundle(
                stations_path=args.stations_csv,
                results_path=args.results_csv,
                advisories_path=args.advisories_csv,
                max_results_rows=args.max_results_rows,
            )
        if args.merge_ceden:
            ceden_sites_path = _resolve_ceden_resource_path(
                requested_path=args.ceden_sites_csv,
                raw_dir=raw_dir,
                default_raw_filename=CEDEN_FIB_SITES_FILENAME,
                resource_url=CEDEN_FIB_SITES_URL,
            )
            ceden_sites_raw = load_ceden_csv(ceden_sites_path)
            if args.max_ceden_rows is not None:
                station_codes = sorted(
                    {
                        str(code).strip()
                        for code in bundle["stations"].get("station_code", pd.Series(dtype=str)).dropna().tolist()
                        if str(code).strip()
                    }
                )
                subset_cache_path = _ceden_subset_cache_path(
                    requested_path=args.ceden_results_csv,
                    raw_dir=raw_dir,
                )
                if subset_cache_path.exists() and not args.force_ceden_fetch:
                    ceden_results_raw = load_ceden_csv(subset_cache_path, nrows=args.max_ceden_rows)
                else:
                    ceden_results_raw = fetch_ceden_datastore_subset(
                        resource_id=_ceden_results_resource_id_for_path(args.ceden_results_csv),
                        station_codes=station_codes,
                        max_rows=args.max_ceden_rows,
                        cache_path=subset_cache_path,
                    )
            else:
                ceden_results_path = _find_existing_ceden_resource_path(
                    requested_path=args.ceden_results_csv,
                    raw_dir=raw_dir,
                    default_raw_filename=Path(CEDEN_FIB_RESULTS_2020_PRESENT_URL).name,
                )
                if ceden_results_path is None:
                    ceden_results_path = _resolve_ceden_resource_path(
                        requested_path=args.ceden_results_csv,
                        raw_dir=raw_dir,
                        default_raw_filename=Path(CEDEN_FIB_RESULTS_2020_PRESENT_URL).name,
                        resource_url=_ceden_results_url_for_path(args.ceden_results_csv),
                    )
                ceden_results_path = _resolve_ceden_resource_path(
                    requested_path=ceden_results_path,
                    raw_dir=raw_dir,
                    default_raw_filename=Path(CEDEN_FIB_RESULTS_2020_PRESENT_URL).name,
                    resource_url=_ceden_results_url_for_path(ceden_results_path),
                )
                ceden_results_raw = load_ceden_csv(ceden_results_path, nrows=args.max_ceden_rows)
            bundle = merge_ceden_into_beachwatch_bundle(
                stations=bundle["stations"],
                observations=bundle["observations"],
                advisories=bundle["advisories"],
                ceden_results_raw=ceden_results_raw,
                ceden_sites_raw=ceden_sites_raw,
                stv_threshold=settings.epa_marine_enterococcus_stv,
            )
            if args.max_ceden_rows is not None and bundle.get("ceden_observations", pd.DataFrame()).empty:
                print(
                    "[warn] The capped Safe-to-Swim slice did not contribute any mapped enterococcus rows. "
                    "Try increasing --max-ceden-rows or removing the cap."
                )
        uv_daily = pd.DataFrame()
        if args.with_external_covariates:
            bundle["stations"], bundle["beach_day"], uv_daily = asyncio.run(
                enrich_beach_day_with_external_covariates(
                    bundle["stations"],
                    bundle["beach_day"],
                    assert_covariates=True,  # Fail loudly if CDIP columns are all-null post-merge
                )
            )
            
        if args.with_hydrology:
            from datetime import date as _date
            from app.data.connectors.hydrology_sources import (
                UsgsNwisConnector,
                OpenMeteoHistoricalPrecipConnector,
            )
            from app.data.pipeline.hydrography import build_hydrologic_beach_links
            from app.data.pipeline.precipitation import aggregate_precip_windows
            from app.data.pipeline.hydrology import aggregate_streamflow_windows, build_beach_hydrology_daily

            _full_start_date = _date(2020, 1, 1)
            end_date = _date.fromisoformat(args.end_date) if args.end_date else _date.today()

            # --- Hydrologic beach links ---
            if args.build_hydrologic_links:
                hydrologic_links = build_hydrologic_beach_links(bundle["stations"])
                hydrologic_links.to_parquet(Path(settings.curated_dir) / "hydrologic_beach_links.parquet", index=False)
            elif args.hydrologic_links_csv:
                hydrologic_links = pd.read_csv(args.hydrologic_links_csv)
            else:
                hydrologic_links_path = Path(settings.curated_dir) / "hydrologic_beach_links.parquet"
                if hydrologic_links_path.exists():
                    hydrologic_links = pd.read_parquet(hydrologic_links_path)
                else:
                    hydrologic_links = build_hydrologic_beach_links(bundle["stations"])
                    hydrologic_links.to_parquet(hydrologic_links_path, index=False)

            # --- Streamflow: incremental fetch from USGS NWIS ---
            gage_ids = (
                hydrologic_links["nearest_stream_gage_id"].dropna().unique().tolist()
                if not hydrologic_links.empty and "nearest_stream_gage_id" in hydrologic_links.columns
                else []
            )
            if args.usgs_gages_csv:
                raw_streamflow = pd.read_csv(args.usgs_gages_csv)
                streamflow_daily = aggregate_streamflow_windows(raw_streamflow)
            else:
                _sf_path = Path(settings.curated_dir) / "streamflow_daily.parquet"
                if not args.start_date and _sf_path.exists():
                    # Incremental: fetch only from the last stored date (- 7 days overlap).
                    _existing_sf = pd.read_parquet(_sf_path)
                    _sf_max = pd.to_datetime(_existing_sf["sample_date"]).max().date() if "sample_date" in _existing_sf.columns else _full_start_date
                    _sf_fetch_start = max(_full_start_date, (pd.Timestamp(_sf_max) - pd.Timedelta(days=7)).date())
                    print(f"[hydrology] streamflow incremental fetch {_sf_fetch_start} → {end_date}")
                else:
                    _sf_fetch_start = _date.fromisoformat(args.start_date) if args.start_date else _full_start_date
                    print(f"[hydrology] streamflow full fetch {_sf_fetch_start} → {end_date}")
                if gage_ids:
                    raw_streamflow_delta = asyncio.run(
                        UsgsNwisConnector().fetch_streamflow(gage_ids, _sf_fetch_start, end_date)
                    )
                else:
                    raw_streamflow_delta = pd.DataFrame()
                # Merge delta on top of existing, deduplicate on (site_no, dateTime)
                if _sf_path.exists() and not args.start_date:
                    _existing_sf = pd.read_parquet(_sf_path)
                    raw_streamflow_delta_agg = aggregate_streamflow_windows(raw_streamflow_delta)
                    _key = [c for c in ("gage_id", "sample_date") if c in _existing_sf.columns and c in raw_streamflow_delta_agg.columns]
                    if _key:
                        streamflow_daily = (
                            pd.concat([_existing_sf, raw_streamflow_delta_agg], ignore_index=True)
                            .drop_duplicates(subset=_key, keep="last")
                            .sort_values(_key)
                            .reset_index(drop=True)
                        )
                    else:
                        streamflow_daily = raw_streamflow_delta_agg
                else:
                    streamflow_daily = aggregate_streamflow_windows(raw_streamflow_delta)
            streamflow_daily.to_parquet(Path(settings.curated_dir) / "streamflow_daily.parquet", index=False)
            print(f"[hydrology] streamflow_daily: {len(streamflow_daily)} rows")

            # --- Precipitation: incremental fetch from Open-Meteo ERA5 ---
            if args.cnrfc_observed_csv:
                raw_precip = pd.read_csv(args.cnrfc_observed_csv)
                precip_daily = aggregate_precip_windows(raw_precip)
            elif not hydrologic_links.empty:
                coords_df = (
                    hydrologic_links[["pour_point_latitude", "pour_point_longitude"]]
                    .dropna()
                    .drop_duplicates()
                )
                locations = list(zip(
                    coords_df["pour_point_latitude"].tolist(),
                    coords_df["pour_point_longitude"].tolist(),
                ))
                _pr_path = Path(settings.curated_dir) / "precip_daily.parquet"
                # The cached precip_daily is only safe to fetch incrementally (last
                # 7 days) when it already carries the *derived* columns. When a new
                # derived column is added (e.g. first_rain_score / precip_*_prior),
                # the historical cached rows lack it and an incremental fetch leaves
                # them NaN forever — the feature reads ~0% covered. Detect that and
                # force a full re-aggregation from the on-disk raw cache (cheap: the
                # Open-Meteo increments are already cached per coord), which self-heals
                # the column for all history. See data-quality note 2026-06-08.
                _PRECIP_DERIVED_COLS = (
                    "precip_mm_96h", "precip_mm_192h",
                    "precip_72h_prior", "precip_168h_prior", "first_rain_score",
                )
                _pr_cache_healthy = False
                if not args.start_date and _pr_path.exists():
                    _existing_pr = pd.read_parquet(_pr_path)
                    _pr_cache_healthy = all(
                        c in _existing_pr.columns and _existing_pr[c].notna().mean() > 0.5
                        for c in _PRECIP_DERIVED_COLS
                    )
                if not args.start_date and _pr_path.exists() and _pr_cache_healthy:
                    _pr_max = pd.to_datetime(_existing_pr["sample_date"]).max().date() if "sample_date" in _existing_pr.columns else _full_start_date
                    _pr_fetch_start = max(_full_start_date, (pd.Timestamp(_pr_max) - pd.Timedelta(days=7)).date())
                    print(f"[hydrology] precip incremental fetch {_pr_fetch_start} → {end_date}")
                else:
                    _pr_fetch_start = _date.fromisoformat(args.start_date) if args.start_date else _full_start_date
                    if _pr_path.exists() and not _pr_cache_healthy:
                        print(f"[hydrology] precip cache missing derived cols → FULL re-aggregation {_pr_fetch_start} → {end_date}")
                    else:
                        print(f"[hydrology] precip full fetch {_pr_fetch_start} → {end_date}")
                raw_precip = asyncio.run(
                    OpenMeteoHistoricalPrecipConnector().fetch_historical_precip(
                        locations,
                        _pr_fetch_start,
                        end_date,
                        cache_dir=settings.precip_cache_dir / "openmeteo",
                    )
                )
                new_precip_daily = aggregate_precip_windows(raw_precip)
                if _pr_path.exists() and not args.start_date:
                    _existing_pr = pd.read_parquet(_pr_path)
                    _pr_key = [c for c in ("latitude", "longitude", "sample_date") if c in _existing_pr.columns and c in new_precip_daily.columns]
                    if _pr_key:
                        precip_daily = (
                            pd.concat([_existing_pr, new_precip_daily], ignore_index=True)
                            .drop_duplicates(subset=_pr_key, keep="last")
                            .sort_values(_pr_key)
                            .reset_index(drop=True)
                        )
                    else:
                        precip_daily = new_precip_daily
                else:
                    precip_daily = new_precip_daily
            else:
                precip_daily = pd.DataFrame()
            precip_daily.to_parquet(Path(settings.curated_dir) / "precip_daily.parquet", index=False)
            print(f"[hydrology] precip_daily: {len(precip_daily)} rows")

            # --- Join hydrology onto beach-day ---
            beach_hydro = build_beach_hydrology_daily(hydrologic_links, streamflow_daily, precip_daily)
            if not beach_hydro.empty:
                beach_hydro["sample_date"] = pd.to_datetime(beach_hydro["sample_date"])
                bundle["beach_day"]["sample_date"] = pd.to_datetime(bundle["beach_day"]["sample_date"])
                bundle["beach_day"] = bundle["beach_day"].merge(
                    beach_hydro, on=["beach_id", "sample_date"], how="left"
                )
                print(f"[hydrology] beach_hydrology_daily joined: {len(beach_hydro)} rows")

        if args.with_solar_wind:
            from datetime import date as _date
            from app.data.connectors.hydrology_sources import OpenMeteoHistoricalSolarWindConnector
            from app.data.pipeline.solar_wind import aggregate_solar_wind_windows
            from app.data.pipeline.marine_microbiology import (
                compute_beach_shore_azimuth,
                compute_beach_coastal_features,
                build_marine_microbiology_daily,
            )

            _full_start_date = _date(2020, 1, 1)
            end_date = _date.fromisoformat(args.end_date) if args.end_date else _date.today()
            stations_df = bundle["stations"].copy()

            # Per-beach static metadata (one-shot, lat/lon-derived)
            shore_az = compute_beach_shore_azimuth(stations_df)
            coastal_feat = compute_beach_coastal_features(stations_df)
            print(f"[solar-wind] shore_azimuth computed for {len(shore_az)} beaches")
            print(f"[solar-wind] coastal proximity flags: {int(coastal_feat['is_near_pier'].sum())} pier-adjacent, "
                  f"{int(coastal_feat['is_near_estuary_mouth'].sum())} estuary-mouth-adjacent")

            # Hourly solar/wind backfill, incremental on disk
            station_locs = list({
                (round(float(r['latitude']), 1), round(float(r['longitude']), 1))
                for _, r in stations_df.iterrows()
                if pd.notna(r.get('latitude')) and pd.notna(r.get('longitude'))
            })
            _sw_path = Path(settings.curated_dir) / "solar_wind_daily.parquet"
            if not args.start_date and _sw_path.exists():
                _existing_sw = pd.read_parquet(_sw_path)
                _sw_max = pd.to_datetime(_existing_sw["sample_date"]).max().date() if "sample_date" in _existing_sw.columns else _full_start_date
                _sw_fetch_start = max(_full_start_date, (pd.Timestamp(_sw_max) - pd.Timedelta(days=7)).date())
                print(f"[solar-wind] incremental fetch {_sw_fetch_start} → {end_date}")
            else:
                _sw_fetch_start = _date.fromisoformat(args.start_date) if args.start_date else _full_start_date
                print(f"[solar-wind] full fetch {_sw_fetch_start} → {end_date}")

            raw_sw = asyncio.run(
                OpenMeteoHistoricalSolarWindConnector().fetch_historical_solar_wind(
                    station_locs,
                    _sw_fetch_start,
                    end_date,
                    cache_dir=settings.precip_cache_dir / "openmeteo_solar_wind",
                )
            )
            new_sw_daily = aggregate_solar_wind_windows(raw_sw)
            if _sw_path.exists() and not args.start_date:
                _existing_sw = pd.read_parquet(_sw_path)
                _sw_key = [c for c in ("station_id", "sample_date") if c in _existing_sw.columns and c in new_sw_daily.columns]
                if _sw_key and not new_sw_daily.empty:
                    sw_daily = (
                        pd.concat([_existing_sw, new_sw_daily], ignore_index=True)
                        .drop_duplicates(subset=_sw_key, keep="last")
                        .sort_values(_sw_key)
                        .reset_index(drop=True)
                    )
                else:
                    sw_daily = _existing_sw if new_sw_daily.empty else new_sw_daily
            else:
                sw_daily = new_sw_daily
            if not sw_daily.empty:
                sw_daily.to_parquet(_sw_path, index=False)
                print(f"[solar-wind] solar_wind_daily: {len(sw_daily)} rows")

                # Map each beach to its nearest open-meteo station_id, then join
                from app.data.pipeline.external_covariates import haversine_km
                sw_stations = (
                    sw_daily[["station_id", "latitude", "longitude"]]
                    .drop_duplicates("station_id")
                    .dropna()
                )
                beach_to_station: dict[str, str] = {}
                for _, b in stations_df.iterrows():
                    if pd.isna(b.get("latitude")) or pd.isna(b.get("longitude")):
                        continue
                    nearest, min_d = None, float("inf")
                    for _, s in sw_stations.iterrows():
                        d = haversine_km(float(b["latitude"]), float(b["longitude"]),
                                         float(s["latitude"]), float(s["longitude"]))
                        if d < min_d:
                            nearest, min_d = str(s["station_id"]), d
                    if nearest:
                        beach_to_station[str(b["beach_id"])] = nearest

                sw_daily["sample_date"] = pd.to_datetime(sw_daily["sample_date"])
                station_to_beaches: dict[str, list[str]] = {}
                for bid, sid in beach_to_station.items():
                    station_to_beaches.setdefault(sid, []).append(bid)
                # Explode station rows per beach
                exploded: list[pd.DataFrame] = []
                for sid, bids in station_to_beaches.items():
                    sub = sw_daily.loc[sw_daily["station_id"] == sid].copy()
                    if sub.empty:
                        continue
                    for bid in bids:
                        s = sub.copy()
                        s["beach_id"] = bid
                        exploded.append(s)
                beach_sw = pd.concat(exploded, ignore_index=True) if exploded else pd.DataFrame()

                if not beach_sw.empty:
                    mm_daily = build_marine_microbiology_daily(beach_sw, shore_az)
                    mm_daily["sample_date"] = pd.to_datetime(mm_daily["sample_date"])
                    bundle["beach_day"]["sample_date"] = pd.to_datetime(bundle["beach_day"]["sample_date"])
                    bundle["beach_day"] = bundle["beach_day"].merge(
                        mm_daily, on=["beach_id", "sample_date"], how="left"
                    )
                    bundle["beach_day"] = bundle["beach_day"].merge(coastal_feat, on="beach_id", how="left")
                    print(f"[solar-wind] marine_microbiology features joined: {len(mm_daily)} rows")

        import numpy as np
        if "beach_day" in bundle and not bundle["beach_day"].empty:
            bd = bundle["beach_day"]
            for col in ["streamflow_cfs_latest", "streamflow_cfs_mean_24h", "streamflow_cfs_max_24h", "streamflow_rising_flag"]:
                if col in bd.columns:
                    bd[col] = bd[col].fillna(0.0)
            if "tidal_height" not in bd.columns or bd["tidal_height"].isna().all():
                days_since_epoch = (pd.to_datetime(bd["sample_date"]) - pd.Timestamp("2000-01-06")).dt.days
                phase = (days_since_epoch % 29.530588) / 29.530588
                bd["tidal_height"] = np.cos(phase * 2 * np.pi) * 1.5
            bundle["beach_day"] = bd

        # Surf-spot aliases: attach surfer names + true break locations to stations so
        # they survive every full refresh (display-only; official name/coords untouched).
        from app.data.pipeline.surf_spots import apply_surf_aliases
        bundle["stations"] = apply_surf_aliases(bundle["stations"])
        print(f"[surf] tagged {int(bundle['stations']['is_surf_spot'].sum())} surf spots")

        write_curated_bundle(
            curated_dir=Path(settings.curated_dir),
            stations=bundle["stations"],
            observations=bundle["observations"],
            advisories=bundle["advisories"],
            beach_day=bundle["beach_day"],
        )
        if not uv_daily.empty:
            uv_daily.to_parquet(Path(settings.curated_dir) / "uv_daily.parquet", index=False)
        write_duckdb_snapshot(
            bundle["beach_day"],
            Path(settings.research_dir) / "surf_health.duckdb",
            "beach_day",
        )
        print(
            json.dumps(
                {name: int(len(frame)) for name, frame in bundle.items() if isinstance(frame, pd.DataFrame)},
                indent=2,
            )
        )

    if args.with_surf:
        from datetime import date as _date
        from app.data.connectors.hydrology_sources import OpenMeteoMarineForecastConnector
        from app.data.pipeline.surf_spots import apply_surf_aliases
        from app.data.pipeline.surf_conditions import build_surf_now, build_surf_daily_forecast

        settings = get_settings()
        curated = Path(settings.curated_dir)
        beaches = pd.read_parquet(curated / "beaches.parquet")
        if "is_surf_spot" not in beaches.columns:
            beaches = apply_surf_aliases(beaches)

        spots = beaches.loc[beaches["is_surf_spot"] == True].copy()  # noqa: E712
        spots["station_id"] = (
            spots["surf_latitude"].round(1).astype(str) + "_" + spots["surf_longitude"].round(1).astype(str)
        )
        print(f"[surf] fetching marine forecast for {len(spots)} surf spots")

        locations = [
            (float(r["surf_latitude"]), float(r["surf_longitude"]))
            for _, r in spots.iterrows()
            if pd.notna(r["surf_latitude"]) and pd.notna(r["surf_longitude"])
        ]
        raw = asyncio.run(
            OpenMeteoMarineForecastConnector(forecast_days=args.surf_forecast_days).fetch_marine_forecast(
                locations,
                _date.today(),
                cache_dir=settings.precip_cache_dir / "openmeteo_marine",
            )
        )
        if raw.empty:
            print("[surf] marine forecast returned no data; skipping surf artifacts")
        else:
            meta = spots[["beach_id", "surf_name", "county", "region", "station_id"]]
            now = build_surf_now(raw, pd.Timestamp.now(tz="UTC"))
            now = meta.merge(now, on="station_id", how="inner")
            daily = build_surf_daily_forecast(raw)
            daily = meta.merge(daily, on="station_id", how="inner")

            now.to_parquet(curated / "surf_now.parquet", index=False)
            daily.to_parquet(curated / "surf_daily_forecast.parquet", index=False)
            print(f"[surf] wrote surf_now ({len(now)} spots) + surf_daily_forecast ({len(daily)} rows)")

    if args.with_hourly:
        from app.data.pipeline.hourly_forecast import build_hourly_forecast

        curated = Path(settings.curated_dir)
        beaches = pd.read_parquet(curated / "beaches.parquet")
        hourly = build_hourly_forecast(beaches)
        hourly.to_parquet(curated / "hourly_forecast.parquet", index=False)
        n_cells = len(hourly)
        n_coords = beaches[["latitude", "longitude"]].dropna().round(1).drop_duplicates().shape[0]
        print(f"[hourly] wrote hourly_forecast.parquet ({n_cells}/{n_coords} grid cells covered)")


if __name__ == "__main__":
    main()
