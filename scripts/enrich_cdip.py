#!/usr/bin/env python3
"""
Patch CDIP wave covariates onto an existing curated beach_day.parquet.

Use this when the curated parquets are already built but were run without
--with-external-covariates (i.e. wave_height_m is missing/all-null).

Usage (from repo root, venv active):
    python scripts/enrich_cdip.py

Reads:
    data/curated/beaches.parquet
    data/curated/beach_day.parquet

Writes (in-place, originals backed up as *.pre-cdip.parquet):
    data/curated/beach_day.parquet   — with wave_height_m, dominant_period_s,
                                       wave_direction_deg, cdip_station_id,
                                       cdip_distance_km columns added
    data/curated/beaches.parquet     — with cdip_station_id, cdip_station_name,
                                       cdip_distance_km columns added
    data/curated/uv_daily.parquet    — EPA UV index by zip/date
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from pathlib import Path

import pandas as pd

# ── repo path setup ──────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.data.pipeline.external_covariates import (  # noqa: E402
    enrich_beach_day_with_external_covariates,
)
from app.data.pipeline.curation import write_duckdb_snapshot  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("enrich_cdip")

CURATED_DIR = REPO_ROOT / "data" / "curated"
RESEARCH_DIR = REPO_ROOT / "data" / "research"


def backup(path: Path) -> None:
    backup_path = path.with_suffix(".pre-cdip.parquet")
    if not backup_path.exists():
        shutil.copy2(path, backup_path)
        log.info("backed up %s → %s", path.name, backup_path.name)
    else:
        log.info("backup already exists: %s (skipping)", backup_path.name)


def main() -> None:
    stations_path = CURATED_DIR / "beaches.parquet"
    beach_day_path = CURATED_DIR / "beach_day.parquet"

    if not stations_path.exists():
        sys.exit(f"ERROR: {stations_path} not found. Run the full pipeline first.")
    if not beach_day_path.exists():
        sys.exit(f"ERROR: {beach_day_path} not found. Run the full pipeline first.")

    log.info("loading stations (%s) …", stations_path)
    stations = pd.read_parquet(stations_path)

    log.info("loading beach_day (%s rows) …", "?")
    beach_day = pd.read_parquet(beach_day_path)
    log.info("beach_day: %d rows, %d cols", len(beach_day), len(beach_day.columns))

    # Drop any pre-existing CDIP/ERDDAP columns so we get a clean merge
    drop_cols = [
        c for c in beach_day.columns
        if c in {
            "cdip_station_id", "cdip_station_name", "cdip_distance_km",
            "wave_height_m", "dominant_period_s", "wave_direction_deg",
            "erddap_source_name", "erddap_distance_km",
            "salinity_psu", "water_temperature_c",
        }
    ]
    if drop_cols:
        log.info("dropping stale columns: %s", drop_cols)
        beach_day = beach_day.drop(columns=drop_cols)

    drop_station_cols = [
        c for c in stations.columns
        if c in {"cdip_station_id", "cdip_station_name", "cdip_distance_km",
                 "erddap_source_name", "erddap_distance_km"}
    ]
    if drop_station_cols:
        stations = stations.drop(columns=drop_station_cols)

    log.info("starting external covariate enrichment (CDIP + ERDDAP + EPA UV) …")
    log.info("this will fetch ~%d CDIP station time-series — expect 3–10 min",
             stations["latitude"].notna().sum())

    stations_enriched, beach_day_enriched, uv_daily = asyncio.run(
        enrich_beach_day_with_external_covariates(
            stations,
            beach_day,
            assert_covariates=True,   # fail loudly if CDIP is still broken
        )
    )

    # ── report ────────────────────────────────────────────────────────────────
    wh_col = "wave_height_m"
    if wh_col in beach_day_enriched.columns:
        n_filled = beach_day_enriched[wh_col].notna().sum()
        pct = 100 * n_filled / len(beach_day_enriched)
        log.info("wave_height_m: %d / %d rows filled (%.1f%%)", n_filled, len(beach_day_enriched), pct)
    else:
        log.warning("wave_height_m column still missing after enrichment!")

    # ── backup originals ──────────────────────────────────────────────────────
    backup(stations_path)
    backup(beach_day_path)

    # ── write enriched parquets ───────────────────────────────────────────────
    stations_enriched.to_parquet(stations_path, index=False)
    log.info("wrote %s (%d rows)", stations_path.name, len(stations_enriched))

    beach_day_enriched.to_parquet(beach_day_path, index=False)
    log.info("wrote %s (%d rows)", beach_day_path.name, len(beach_day_enriched))

    if not uv_daily.empty:
        uv_path = CURATED_DIR / "uv_daily.parquet"
        uv_daily.to_parquet(uv_path, index=False)
        log.info("wrote %s (%d rows)", uv_path.name, len(uv_daily))

    # ── update DuckDB snapshot ────────────────────────────────────────────────
    duckdb_path = RESEARCH_DIR / "surf_health.duckdb"
    if duckdb_path.exists():
        write_duckdb_snapshot(beach_day_enriched, duckdb_path, "beach_day")
        log.info("updated DuckDB snapshot at %s", duckdb_path)

    log.info("done. Next step: retrain models, regenerate forecasts, commit parquets, push → redeploy.")


if __name__ == "__main__":
    main()
