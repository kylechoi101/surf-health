from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import duckdb
import pandas as pd


def write_duckdb_snapshot(frame: pd.DataFrame, snapshot_path: Path, table_name: str) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(snapshot_path))
    try:
        connection.register("frame", frame)
        connection.execute(f"create or replace table {table_name} as select * from frame")
    finally:
        connection.close()


def curate_beach_days(
    bacteria_frame: pd.DataFrame,
    covariate_frames: Iterable[pd.DataFrame],
    stv_threshold: float,
) -> pd.DataFrame:
    if bacteria_frame.empty:
        return pd.DataFrame()

    frame = bacteria_frame.copy()
    frame["sample_date"] = pd.to_datetime(frame["sample_time"]).dt.date
    frame["enterococcus_value"] = pd.to_numeric(frame["enterococcus_value"], errors="coerce")
    # Local-dev fixture path only. The sample rows carry no method/units, so they
    # stand in for culture sampling and the culture action value is the divisor.
    # Emitted so a fixture-built beach_day has the same schema the model expects.
    frame["enterococcus_action_ratio"] = frame["enterococcus_value"] / float(stv_threshold)
    frame["exceeds_stv"] = (frame["enterococcus_value"] > stv_threshold).astype("Int64")

    covariates = [item for item in covariate_frames if not item.empty]
    if covariates:
        covariate_frame = covariates[0].copy()
        frame = frame.merge(covariate_frame, on=["beach_id", "sample_date"], how="left")

    return frame.sort_values(["beach_id", "sample_date"]).reset_index(drop=True)

