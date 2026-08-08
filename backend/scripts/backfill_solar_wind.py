#!/usr/bin/env python
"""One-off historical backfill of the Open-Meteo weather covariates.

Step 2 of the rebuild programme (``REBUILD_STEPS.md``). Fills the hole behind the
seven weather-derived "marine microbiology" features, which as of the
2026-08-07 baseline are present on 26.7% of the 1095-day training window
(UV: 8.9%) and silently zero-filled everywhere else.

What it does, in order:

1. Enumerate the distinct 0.1° grid cells covering every **California** beach in
   ``beaches.parquet`` (120 cells for 850 beaches — the cache is keyed by cell,
   so this is a ~120-key job, not an 850-key one). Texas coordinates left over in
   the cache from the rejected TX-pooling experiment are never fetched.
2. Fetch hourly ERA5 cloud / shortwave / wind per (cell, calendar year) from the
   archive API, and hourly real UV per (cell, year) from the air-quality archive
   (which starts 2022-08-04 — see ``UV_ARCHIVE_EARLIEST_DATE``).
3. Aggregate to forecast-safe daily windows **per cell over its whole history at
   once**, so the 24-hour windows and the ``days_since_sunny`` running counter do
   not reset at a chunk boundary.
4. Merge into ``data/curated/solar_wind_daily.parquet``.
5. Optionally (``--apply-to-beach-day``) re-join the derived features onto the
   existing ``beach_day.parquet``, replacing exactly the eight solar-wind-derived
   columns and touching nothing else — no relabelling, no row-count change.

Resumability: every (cell, year) fetch is its own parquet cache file, and the
connectors return the cached file without a network call. Re-running after an
interrupt therefore costs one chunk of redundant work at most. ``--state-file``
additionally records completed chunks so progress is greppable mid-run.

Rate limiting: Open-Meteo's free tier throttles by request weight. Requests run
at the connectors' own ``concurrency`` (5) with a configurable inter-chunk pause,
and any HTTP 429 triggers exponential backoff before the chunk is retried.

Usage::

    cd backend
    .venv/bin/python scripts/backfill_solar_wind.py --start 2020-01-01
    .venv/bin/python scripts/backfill_solar_wind.py --apply-to-beach-day
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.data.connectors.hydrology_sources import (  # noqa: E402
    UV_ARCHIVE_EARLIEST_DATE,
    OpenMeteoHistoricalSolarWindConnector,
    OpenMeteoHistoricalUvConnector,
)
from app.data.pipeline.marine_microbiology import (  # noqa: E402
    build_marine_microbiology_daily,
    compute_beach_shore_azimuth,
)
from app.data.pipeline.solar_wind import (  # noqa: E402
    SOLAR_WIND_DERIVED_COLUMNS,
    aggregate_solar_wind_windows,
    explode_solar_wind_to_beaches,
    merge_uv_hourly,
)

# Generous bounding box around California. The solar-wind cache also holds 83
# Texas files from the rejected TX-pooling experiment; fetching history for those
# would be pure waste, so coordinates are filtered rather than taken from the
# cache directory listing.
CA_BBOX = (32.0, 42.5, -125.5, -114.0)  # lat_min, lat_max, lon_min, lon_max

DEFAULT_START = date(2020, 1, 1)


def ca_grid_cells(beaches: pd.DataFrame) -> list[tuple[float, float]]:
    """Distinct 0.1° (lat, lon) cells covering CA beaches, in a stable order."""
    df = beaches.dropna(subset=["latitude", "longitude"])
    cells: set[tuple[float, float]] = set()
    skipped = 0
    for row in df.itertuples():
        lat, lon = round(float(row.latitude), 1), round(float(row.longitude), 1)
        if not (CA_BBOX[0] <= lat <= CA_BBOX[1] and CA_BBOX[2] <= lon <= CA_BBOX[3]):
            skipped += 1
            continue
        cells.add((lat, lon))
    if skipped:
        print(f"[backfill] skipped {skipped} beaches outside the CA bounding box")
    return sorted(cells)


def year_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end] on calendar-year boundaries.

    Year-sized chunks are the checkpoint granularity: small enough that an
    interrupt loses ~1 cell-year, large enough that 120 cells × 7 years is ~840
    requests rather than tens of thousands.
    """
    out: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        year_end = min(date(cursor.year, 12, 31), end)
        out.append((cursor, year_end))
        cursor = date(cursor.year + 1, 1, 1)
    return out


class Checkpoint:
    """Append-only record of completed (kind, cell, chunk) fetches."""

    def __init__(self, path: Path | None):
        self.path = path
        self.done: set[str] = set()
        if path and path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line:
                    self.done.add(line)
            print(f"[backfill] checkpoint: {len(self.done)} chunks already recorded")

    def key(self, kind: str, cell: tuple[float, float], chunk: tuple[date, date]) -> str:
        return f"{kind}|{cell[0]}|{cell[1]}|{chunk[0]}|{chunk[1]}"

    def mark(self, key: str) -> None:
        self.done.add(key)
        if self.path:
            with self.path.open("a") as fh:
                fh.write(key + "\n")


def station_id(cell: tuple[float, float]) -> str:
    return f"{cell[0]}_{cell[1]}"


async def _fetch_verified(
    coro_factory,
    expected: set[str],
    *,
    label: str,
    max_attempts: int = 8,
) -> pd.DataFrame:
    """Fetch a chunk and do not return until every expected cell is present.

    The connectors deliberately swallow per-coordinate HTTP failures — they log
    and return an empty frame so one bad coordinate cannot kill a daily run. For
    a *backfill* that behaviour is a data-integrity hazard: Open-Meteo answers
    **429 Too Many Requests** under sustained load, the connector eats it, and the
    chunk comes back short with no exception anywhere. The first run of this
    script silently dropped whole cell-years that way.

    So completeness is checked here, against the station ids that were asked for,
    and a short result is retried with exponential backoff exactly like a raised
    error. ``AllNullVariableError`` is re-raised immediately — it is a config bug
    and no amount of waiting fixes it.
    """
    delay = 20.0
    last: pd.DataFrame = pd.DataFrame()
    for attempt in range(1, max_attempts + 1):
        try:
            last = await coro_factory()
        except Exception as exc:  # noqa: BLE001 - classified immediately below
            if exc.__class__.__name__ == "AllNullVariableError" or attempt == max_attempts:
                raise
            print(f"[backfill] {label} attempt {attempt} raised {type(exc).__name__}; "
                  f"retrying in {delay:.0f}s", flush=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 600.0)
            continue

        got = set(last["station_id"].unique()) if last is not None and not last.empty else set()
        missing = expected - got
        if not missing:
            return last
        if attempt == max_attempts:
            raise RuntimeError(
                f"{label}: {len(missing)} of {len(expected)} cells still missing after "
                f"{max_attempts} attempts ({sorted(missing)[:5]}). Refusing to aggregate a "
                "frame with holes in it."
            )
        print(
            f"[backfill] {label} incomplete ({len(got)}/{len(expected)} cells) — almost "
            f"certainly rate limiting; backing off {delay:.0f}s",
            flush=True,
        )
        await asyncio.sleep(delay)
        delay = min(delay * 2, 600.0)
    return last


def run_backfill(
    cells: list[tuple[float, float]],
    start: date,
    end: date,
    *,
    sw_cache: Path,
    uv_cache: Path,
    checkpoint: Checkpoint,
    pause_s: float,
    skip_uv: bool,
    batch_size: int,
) -> pd.DataFrame:
    """Fetch every (cell, year) chunk and aggregate to daily rows per cell.

    Cells are fetched in batches so the connectors' internal ``concurrency`` (5)
    actually engages — a one-coordinate call serialises at ~2.5 s/request, which
    turns 120 cells into an hour of mostly-idle waiting. Each cell's cache files
    are still per-coordinate, so batching changes throughput and nothing else.
    """
    sw_conn = OpenMeteoHistoricalSolarWindConnector()
    uv_conn = OpenMeteoHistoricalUvConnector()
    chunks = year_chunks(start, end)
    uv_chunks = year_chunks(max(start, UV_ARCHIVE_EARLIEST_DATE), end)

    batches = [cells[i : i + batch_size] for i in range(0, len(cells), batch_size)]
    total = len(cells) * (len(chunks) + (0 if skip_uv else len(uv_chunks)))
    print(
        f"[backfill] {len(cells)} CA grid cells in {len(batches)} batches of {batch_size} "
        f"x {len(chunks)} year chunks (+{0 if skip_uv else len(uv_chunks)} UV chunks) "
        f"= {total} fetches; {start} → {end}",
        flush=True,
    )

    daily_frames: list[pd.DataFrame] = []
    t0 = time.time()
    done = 0
    cells_done = 0
    for bi, batch in enumerate(batches, 1):
        expected = {station_id(c) for c in batch}
        sw_raw: list[pd.DataFrame] = []
        for chunk in chunks:
            frame = asyncio.run(
                _fetch_verified(
                    lambda c=chunk: sw_conn.fetch_historical_solar_wind(
                        list(batch), c[0], c[1], cache_dir=sw_cache
                    ),
                    expected,
                    label=f"sw batch{bi} {chunk[0].year}",
                )
            )
            sw_raw.append(frame)
            for cell in batch:
                checkpoint.mark(checkpoint.key("sw", cell, chunk))
            done += len(batch)
            if pause_s:
                time.sleep(pause_s)

        uv_raw: list[pd.DataFrame] = []
        if not skip_uv:
            for chunk in uv_chunks:
                frame = asyncio.run(
                    _fetch_verified(
                        lambda c=chunk: uv_conn.fetch_historical_uv(
                            list(batch), c[0], c[1], cache_dir=uv_cache
                        ),
                        expected,
                        label=f"uv batch{bi} {chunk[0].year}",
                    )
                )
                uv_raw.append(frame)
                for cell in batch:
                    checkpoint.mark(checkpoint.key("uv", cell, chunk))
                done += len(batch)
                if pause_s:
                    time.sleep(pause_s)

        if not sw_raw:
            print(f"[backfill] batch {bi}/{len(batches)} {batch}: NO DATA", flush=True)
            continue

        raw_all = pd.concat(sw_raw, ignore_index=True)
        uv_all = pd.concat(uv_raw, ignore_index=True) if uv_raw else pd.DataFrame()
        raw_all = merge_uv_hourly(raw_all, uv_all)

        # Aggregate PER CELL over its whole history in one call: the 24 h windows
        # and the days_since_sunny counter are per-station running quantities, so
        # aggregating year by year would truncate them at every boundary.
        for _cell_id, sub in raw_all.groupby("station_id", sort=False):
            daily = aggregate_solar_wind_windows(sub)
            if not daily.empty:
                daily_frames.append(daily)
            cells_done += 1

        elapsed = time.time() - t0
        rate = done / elapsed if elapsed else 0.0
        eta = (total - done) / rate if rate else float("nan")
        real_uv = float((~raw_all["uv_index"].isna()).mean()) if "uv_index" in raw_all else 0.0
        print(
            f"[backfill] batch {bi}/{len(batches)}: {len(raw_all)} hourly rows, "
            f"{cells_done} cells aggregated, real-UV hours {real_uv:.0%} | "
            f"{done}/{total} fetches, {rate:.1f}/s, ETA {eta / 60:.1f} min",
            flush=True,
        )

    if not daily_frames:
        return pd.DataFrame()
    out = pd.concat(daily_frames, ignore_index=True)

    # Completeness audit. A silently short fetch is the failure mode this whole
    # step exists to stop repeating, so say plainly which cells came back thin.
    expected_days = (end - start).days + 1
    per_cell = out.groupby("station_id")["sample_date"].nunique()
    missing_cells = sorted({station_id(c) for c in cells} - set(per_cell.index))
    thin = per_cell[per_cell < expected_days * 0.98]
    print(
        f"[backfill] completeness: {len(per_cell)}/{len(cells)} cells produced daily rows; "
        f"median {int(per_cell.median())} of {expected_days} expected days",
        flush=True,
    )
    if missing_cells:
        print(f"[backfill] ⚠ {len(missing_cells)} cells produced NOTHING: {missing_cells[:10]}")
    if len(thin):
        print(f"[backfill] ⚠ {len(thin)} cells under 98% of expected days: "
              f"{thin.head(10).to_dict()}")
    return out


def merge_into_solar_wind_daily(new_daily: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Union the backfill into solar_wind_daily.parquet, newest write winning.

    ``keep="last"`` means the backfilled row replaces a previously cached row for
    the same (station_id, sample_date). That is intended: the historical cache
    only ever held 2026 rows, and those were aggregated before ``uv_index_24h_max``
    and ``wind_direction_24h_mean`` existed, so they carry NaN for both.
    """
    new_daily = new_daily.copy()
    new_daily["sample_date"] = pd.to_datetime(new_daily["sample_date"]).dt.date
    if path.exists():
        existing = pd.read_parquet(path)
        existing["sample_date"] = pd.to_datetime(existing["sample_date"]).dt.date
        combined = pd.concat([existing, new_daily], ignore_index=True)
    else:
        combined = new_daily
    combined = (
        combined.drop_duplicates(subset=["station_id", "sample_date"], keep="last")
        .sort_values(["station_id", "sample_date"])
        .reset_index(drop=True)
    )
    if "uv_index_is_proxy" in combined.columns:
        # Nullable boolean, not object: rows carried over from a pre-backfill
        # vintage predate the column and are legitimately "provenance unknown",
        # which `bool` cannot represent and object dtype represents ambiguously.
        combined["uv_index_is_proxy"] = combined["uv_index_is_proxy"].astype("boolean")
    return combined


def apply_to_beach_day(
    beach_day_path: Path, beaches_path: Path, sw_daily: pd.DataFrame
) -> tuple[pd.DataFrame, dict]:
    """Recompute the eight solar-wind-derived columns on the existing beach_day.

    Surgical on purpose. Running the full pipeline CLI to rebuild these features
    would also re-normalise BeachWatch, re-merge CEDEN and re-pull the live feed —
    i.e. it would move the label, which Step 2 must not do. This replaces exactly
    ``SOLAR_WIND_DERIVED_COLUMNS`` and leaves every other column, the row count
    and the row order untouched.
    """
    bd = pd.read_parquet(beach_day_path)
    stations = pd.read_parquet(beaches_path)
    before_rows, before_cols = len(bd), list(bd.columns)

    shore_az = compute_beach_shore_azimuth(stations)
    beach_sw = explode_solar_wind_to_beaches(sw_daily, stations)
    if beach_sw.empty:
        raise SystemExit("[apply] no beach-level solar/wind rows; refusing to write")
    mm_daily = build_marine_microbiology_daily(beach_sw, shore_az)
    mm_daily["sample_date"] = pd.to_datetime(mm_daily["sample_date"])
    dupes = mm_daily.duplicated(subset=["beach_id", "sample_date"]).sum()
    if dupes:
        raise SystemExit(f"[apply] {dupes} duplicate (beach_id, sample_date) rows — merge would fan out")

    bd["sample_date"] = pd.to_datetime(bd["sample_date"])
    replace = [c for c in SOLAR_WIND_DERIVED_COLUMNS if c in mm_daily.columns]
    merged = bd.drop(columns=replace, errors="ignore").merge(
        mm_daily[["beach_id", "sample_date"] + replace],
        on=["beach_id", "sample_date"],
        how="left",
    )
    # Restore the original column order so the parquet schema is byte-comparable
    # apart from the values that changed.
    merged = merged[[c for c in before_cols if c in merged.columns]]
    if len(merged) != before_rows:
        raise SystemExit(f"[apply] row count changed {before_rows} → {len(merged)}; refusing to write")
    if list(merged.columns) != before_cols:
        raise SystemExit("[apply] column set changed; refusing to write")

    stats = {
        "rows": int(len(merged)),
        "coverage": {c: round(float(merged[c].notna().mean()), 4) for c in replace},
    }
    return merged, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    ap.add_argument("--end", type=date.fromisoformat, default=None, help="default: today")
    ap.add_argument("--limit-cells", type=int, default=None, help="benchmark on the first N cells")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds to sleep between chunk fetches")
    ap.add_argument("--cell-batch", type=int, default=5,
                    help="cells per request batch; matches the connectors' concurrency")
    ap.add_argument("--skip-uv", action="store_true", help="ERA5 only; leave UV on the shortwave proxy")
    ap.add_argument("--state-file", type=Path, default=None)
    ap.add_argument("--apply-to-beach-day", action="store_true",
                    help="also re-join the derived features onto beach_day.parquet")
    ap.add_argument("--fetch", default=True, action=argparse.BooleanOptionalAction,
                    help="--no-fetch reuses solar_wind_daily.parquet as-is (apply step only)")
    ap.add_argument("--report", type=Path, default=None, help="write a JSON run report here")
    args = ap.parse_args()

    settings = get_settings()
    curated = Path(settings.curated_dir)
    sw_path = curated / "solar_wind_daily.parquet"
    end = args.end or datetime.now(timezone.utc).date()

    beaches = pd.read_parquet(curated / "beaches.parquet")
    cells = ca_grid_cells(beaches)
    if args.limit_cells:
        cells = cells[: args.limit_cells]

    t0 = time.time()
    report: dict = {"started_at": datetime.now(timezone.utc).isoformat(), "cells": len(cells)}

    if args.fetch:
        checkpoint = Checkpoint(args.state_file)
        new_daily = run_backfill(
            cells,
            args.start,
            end,
            sw_cache=settings.precip_cache_dir / "openmeteo_solar_wind",
            uv_cache=settings.precip_cache_dir / "openmeteo_uv",
            checkpoint=checkpoint,
            pause_s=args.pause,
            skip_uv=args.skip_uv,
            batch_size=max(1, args.cell_batch),
        )
        if new_daily.empty:
            print("[backfill] no rows produced; nothing written")
            return 1
        combined = merge_into_solar_wind_daily(new_daily, sw_path)
        combined.to_parquet(sw_path, index=False)
        print(f"[backfill] solar_wind_daily.parquet: {len(combined)} rows, "
              f"{combined['station_id'].nunique()} cells, "
              f"{combined['sample_date'].min()} → {combined['sample_date'].max()}")
        report["solar_wind_daily_rows"] = int(len(combined))
        report["fetch_seconds"] = round(time.time() - t0, 1)

    if args.apply_to_beach_day:
        sw_daily = pd.read_parquet(sw_path)
        merged, stats = apply_to_beach_day(
            curated / "beach_day.parquet", curated / "beaches.parquet", sw_daily
        )
        merged.to_parquet(curated / "beach_day.parquet", index=False)
        print(f"[apply] beach_day.parquet rewritten: {stats['rows']} rows")
        for col, cov in stats["coverage"].items():
            print(f"[apply]   {col:28s} {cov:.2%}")
        report["beach_day"] = stats

    report["wall_seconds"] = round(time.time() - t0, 1)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2))
    print(f"[backfill] done in {report['wall_seconds'] / 60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
