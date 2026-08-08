from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import duckdb
import pandas as pd

from app.data.pipeline.exceedance import compute_exceeds_stv


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
    # Method-aware, like every other exceedance in the pipeline. This is the
    # fixture/dev path, but it WRITES beach_day.parquet -- a flat
    # `value > stv_threshold` here would judge San Diego ddPCR copies against
    # the 104 culture STV and overwrite the real label frame with one built on
    # a definition nothing else in the repo uses. Frames without method/units
    # (the sample fixture) fall through as culture, which is the right default.
    blank = pd.Series("", index=frame.index, dtype="object")
    frame["exceeds_stv"] = compute_exceeds_stv(
        frame["enterococcus_value"],
        frame["method"] if "method" in frame.columns else blank,
        frame["units"] if "units" in frame.columns else blank,
        stv_threshold,
    ).astype("Int64")

    covariates = [item for item in covariate_frames if not item.empty]
    if covariates:
        covariate_frame = covariates[0].copy()
        frame = frame.merge(covariate_frame, on=["beach_id", "sample_date"], how="left")

    return frame.sort_values(["beach_id", "sample_date"]).reset_index(drop=True)

