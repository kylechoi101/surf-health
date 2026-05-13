from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

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
    active = recent.loc[recent["status"] == "active"]
    return pd.concat([latest, active], ignore_index=True).drop_duplicates()[columns]


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
        ("health", json.dumps(payload)),
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

    beaches = _load_parquet(curated_dir, "beaches")
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
    advisories = _recent_advisories(_load_parquet(curated_dir, "advisories"))

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
