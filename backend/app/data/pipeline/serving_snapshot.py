from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.core.json_safe import dumps_strict
from app.services.shore_normal import compute_shore_normal_deg

OBSERVATION_LIMIT = 25
ENVIRONMENT_LIMIT = 10
SERVING_SNAPSHOT_NAME = "serving.sqlite"

OBSERVATION_COLUMNS = [
    "beach_id",
    "sample_time",
    "sample_date",
    "analyte",
    "method",
    "units",
    "value",
    "exceeds_stv",
    "weather",
    "storm_drain_flow",
]

RECENT_ENVIRONMENT_COLUMNS = [
    "beach_id",
    "sample_date",
    "wave_height_m",
    "dominant_period_s",
    "water_temperature_c",
    "salinity_psu",
    "weather",
    "storm_drain_flow",
    "tidal_height",
    "surf_height_observed",
    "turbidity_observed",
    # Wind + UV from solar_wind ingest (Open-Meteo ERA5-Land + derived UV).
    # Surface so the mobile/web detail page can render daily sparklines next
    # to the headline value and not just the latest snapshot.
    "wind_speed_24h_max",
    "wind_direction_24h_mean",
    "uv_index_24h_max",
]


def _load_parquet(curated_dir: Path, name: str) -> pd.DataFrame:
    path = curated_dir / f"{name}.parquet"
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def _json_dumps(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return "[]"
    if isinstance(value, float) and pd.isna(value):
        return "[]"
    if hasattr(value, "tolist"):
        value = value.tolist()
    return json.dumps(value)


def _normalize_datetime_columns(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in normalized.columns:
        if pd.api.types.is_datetime64_any_dtype(normalized[column]):
            normalized[column] = normalized[column].apply(
                lambda value: value.isoformat() if pd.notna(value) else None
            )
    return normalized.where(pd.notna(normalized), None)


def _prepare_json_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    prepared = frame.copy()
    for column in columns:
        if column in prepared.columns:
            prepared[column] = prepared[column].apply(_json_dumps)
    return prepared


def _recent_by_beach(
    frame: pd.DataFrame,
    sort_column: str,
    limit: int,
    columns: list[str],
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=columns)

    recent = frame.copy()
    for column in columns:
        if column not in recent.columns:
            recent[column] = None
    recent[sort_column] = pd.to_datetime(recent[sort_column], errors="coerce")
    recent = recent.sort_values(["beach_id", sort_column], ascending=[True, False])
    recent = recent.groupby("beach_id", as_index=False, group_keys=False).head(limit)
    return recent[columns]


ADVISORY_AUTO_EXPIRE_DAYS = 14


def auto_expire_zombie_advisories(advisories: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Demote 'active' rows older than 14d (last_seen_at, else started_at)
    to 'historical' — unless they're Chronic Postings that counties leave
    open intentionally (e.g. Sonoma chronic sites).

    The audit script has been flagging these zombies for months; this is
    the actual action. Returns (frame, n_expired)."""
    if advisories.empty or "status" not in advisories.columns:
        return advisories, 0

    frame = advisories.copy()
    active_mask = frame["status"] == "active"
    if not active_mask.any():
        return frame, 0

    advisory_type = frame.get("advisory_type", pd.Series("", index=frame.index))
    is_chronic = advisory_type.fillna("").str.contains("chronic", case=False, na=False)

    # Prefer last_seen_at when present; otherwise fall back to started_at.
    started = pd.to_datetime(frame.get("started_at"), errors="coerce", utc=True)
    if "last_seen_at" in frame.columns:
        last_seen = pd.to_datetime(frame["last_seen_at"], errors="coerce", utc=True)
        reference = last_seen.fillna(started)
    else:
        reference = started

    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=ADVISORY_AUTO_EXPIRE_DAYS)
    too_old = reference.notna() & (reference < cutoff)
    expire_mask = active_mask & too_old & ~is_chronic
    n_expired = int(expire_mask.sum())
    if n_expired:
        frame.loc[expire_mask, "status"] = "historical"
    return frame, n_expired


def _recent_advisories(advisories: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "beach_id",
        "advisory_type",
        "started_at",
        "ended_at",
        "status",
        "cause",
        "county",
        "advisory_website",
    ]
    if advisories.empty:
        return pd.DataFrame(columns=columns)

    recent = advisories.copy()
    for column in columns:
        if column not in recent.columns:
            recent[column] = None
    recent["started_at"] = pd.to_datetime(recent["started_at"], errors="coerce")
    recent = recent.sort_values(["beach_id", "started_at"], ascending=[True, False])
    latest = recent.groupby("beach_id", as_index=False, group_keys=False).head(10)
    # Only carry currently-active advisories (started within the last 30 days).
    # See filter_currently_active() docstring for rationale — protects against
    # zombie advisories that were never explicitly closed in the source feed.
    from app.repositories.curated_repository import filter_currently_active
    active = filter_currently_active(recent)
    return pd.concat([latest, active], ignore_index=True).drop_duplicates()[columns]


def _attach_shore_normal(beaches: pd.DataFrame) -> pd.DataFrame:
    """Precompute the seaward `shore_normal_deg` bearing for every beach.

    Shore-normal depends only on geography, so baking it into the snapshot
    lets the API read a column instead of running an 850-beach SVD on the
    first /beaches request after each process start (the old cold-cache path
    cost ~12s). The runtime fallback in ServingSnapshotRepository still works
    for legacy snapshots that predate this column.
    """
    required = {"beach_id", "latitude", "longitude"}
    if beaches.empty or not required.issubset(beaches.columns):
        return beaches

    population: list[tuple[str, float, float]] = []
    for bid, lat, lon in zip(
        beaches["beach_id"], beaches["latitude"], beaches["longitude"], strict=False
    ):
        try:
            population.append((str(bid), float(lat), float(lon)))
        except (TypeError, ValueError):
            continue

    beaches = beaches.copy()
    beaches["shore_normal_deg"] = [
        compute_shore_normal_deg(str(bid), population) for bid in beaches["beach_id"]
    ]
    return beaches


def _write_table(conn: sqlite3.Connection, name: str, frame: pd.DataFrame) -> None:
    _normalize_datetime_columns(frame).to_sql(name, conn, if_exists="replace", index=False)


def _write_system_health(conn: sqlite3.Connection, curated_dir: Path) -> None:
    payload: dict = {}
    health_path = curated_dir / "system_health.json"
    if health_path.exists():
        payload = json.loads(health_path.read_text())

    conn.execute("drop table if exists system_health")
    conn.execute("create table system_health (key text primary key, payload text not null)")
    conn.execute(
        "insert into system_health (key, payload) values (?, ?)",
        # Strict: the API reads this row and re-serialises it through Starlette,
        # which renders with allow_nan=False — a NaN here would 500 /system/health.
        ("health", dumps_strict(payload, indent=None)),
    )

    audit_path = curated_dir / "advisory_audit.json"
    if audit_path.exists():
        conn.execute(
            "insert into system_health (key, payload) values (?, ?)",
            ("advisory_audit", audit_path.read_text()),
        )
    conn.execute(
        "insert into system_health (key, payload) values (?, ?)",
        (
            "serving_snapshot",
            json.dumps({"generated_at": datetime.now(UTC).isoformat()}),
        ),
    )


def _create_indices(conn: sqlite3.Connection) -> None:
    index_statements = [
        "create index if not exists idx_beaches_beach_id on beaches(beach_id)",
        "create index if not exists idx_parent_beaches_parent_id on parent_beaches(parent_beach_id)",
        "create index if not exists idx_forecasts_beach_date on forecasts(beach_id, forecast_date)",
        "create index if not exists idx_latest_env_beach_id on latest_env(beach_id)",
        "create index if not exists idx_observations_recent_beach_time "
        "on observations_recent(beach_id, sample_time)",
        "create index if not exists idx_recent_environment_beach_date "
        "on recent_environment(beach_id, sample_date)",
        "create index if not exists idx_advisories_recent_beach_started "
        "on advisories_recent(beach_id, started_at)",
        "create index if not exists idx_advisories_recent_status on advisories_recent(status)",
    ]
    for statement in index_statements:
        conn.execute(statement)


def build_serving_snapshot(curated_dir: Path, output_path: Path | None = None) -> Path:
    curated_dir = Path(curated_dir)
    output_path = output_path or curated_dir / SERVING_SNAPSHOT_NAME
    tmp_path = output_path.with_suffix(".tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    beaches = _attach_shore_normal(_load_parquet(curated_dir, "beaches"))
    parent_beaches = _prepare_json_columns(_load_parquet(curated_dir, "parent_beaches"), ["member_beach_ids"])
    forecasts = _prepare_json_columns(_load_parquet(curated_dir, "forecasts"), ["top_drivers"])
    latest_env = _load_parquet(curated_dir, "latest_env")
    observations = _recent_by_beach(
        _load_parquet(curated_dir, "observations"),
        "sample_time",
        OBSERVATION_LIMIT,
        OBSERVATION_COLUMNS,
    )
    recent_environment = _recent_by_beach(
        _load_parquet(curated_dir, "beach_day"),
        "sample_date",
        ENVIRONMENT_LIMIT,
        RECENT_ENVIRONMENT_COLUMNS,
    )
    # Auto-expire zombie 'active' advisories (>14d, non-Chronic) before any
    # downstream consumer sees them. Persist back to advisories.parquet so
    # the API repositories, audit script, and serving snapshot all agree on
    # the same active set.
    advisories_raw = _load_parquet(curated_dir, "advisories")
    advisories_raw, n_expired = auto_expire_zombie_advisories(advisories_raw)
    if n_expired:
        print(
            f"[serving_snapshot] auto-expired {n_expired} zombie active "
            f"advisories (>{ADVISORY_AUTO_EXPIRE_DAYS}d old, non-Chronic)"
        )
        advisories_path = curated_dir / "advisories.parquet"
        if advisories_path.exists():
            advisories_raw.to_parquet(advisories_path, index=False)
    advisories = _recent_advisories(advisories_raw)

    with sqlite3.connect(tmp_path) as conn:
        conn.execute("pragma journal_mode=off")
        conn.execute("pragma synchronous=off")
        _write_table(conn, "beaches", beaches)
        _write_table(conn, "parent_beaches", parent_beaches)
        _write_table(conn, "forecasts", forecasts)
        _write_table(conn, "latest_env", latest_env)
        _write_table(conn, "observations_recent", observations)
        _write_table(conn, "recent_environment", recent_environment)
        _write_table(conn, "advisories_recent", advisories)
        _write_system_health(conn, curated_dir)
        _create_indices(conn)
        conn.commit()
        conn.execute("vacuum")

    tmp_path.replace(output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the read-only API serving SQLite snapshot.")
    parser.add_argument("--curated", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    print(build_serving_snapshot(args.curated, args.output))


if __name__ == "__main__":
    main()
