"""Which lab assay a beach is currently judged by (culture vs ddPCR), strictly before a date.

Shared by the served logistic model (``logit_challenger``) and the model
comparison harness (``scripts/compare_all_models.py``) so both use one rule.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from app.data.pipeline.sample_key import assay_kind


def derive_label_method_from_observations(curated_dir: Path, beach_day: pd.DataFrame) -> pd.DataFrame:
    """Derive beach_day['label_method'] from observations.parquet if missing."""
    if "label_method" in beach_day.columns:
        return beach_day
    obs_path = Path(curated_dir) / "observations.parquet"
    if not obs_path.exists():
        bd = beach_day.copy()
        bd["label_method"] = "culture"
        return bd
    obs = pd.read_parquet(obs_path)
    obs = obs.copy()
    obs["sample_date"] = pd.to_datetime(obs["sample_date"]).dt.normalize()
    obs["_exceed_rank"] = obs["exceeds_stv"].fillna(False).astype(bool).astype(int)
    value = obs["value"] if "value" in obs.columns else pd.Series(np.nan, index=obs.index)
    obs["_value_rank"] = pd.to_numeric(value, errors="coerce").fillna(float("-inf"))
    sort_cols = ["_exceed_rank", "_value_rank"]
    if "sample_time" in obs.columns:
        sort_cols.append("sample_time")

    worst = (
        obs.sort_values(sort_cols)
        .groupby(["beach_id", "sample_date"], as_index=False)
        .tail(1)
    )
    method_col = worst["method"] if "method" in worst.columns else pd.Series("", index=worst.index)
    units_col = worst["units"] if "units" in worst.columns else pd.Series("", index=worst.index)
    worst["label_method"] = assay_kind(method_col, units_col)

    bd = beach_day.copy()
    bd["sample_date"] = pd.to_datetime(bd["sample_date"]).dt.normalize()
    bd = bd.merge(worst[["beach_id", "sample_date", "label_method"]], on=["beach_id", "sample_date"], how="left")
    bd["label_method"] = bd["label_method"].fillna("culture")
    return bd


def compute_assays(beach_day: pd.DataFrame, beach_ids: Sequence[str], dates: Sequence) -> np.ndarray:
    """The beach's assay = its most recent beach_day.label_method before D (strictly < D)."""
    bids = np.asarray(list(beach_ids), dtype=object)
    qd = pd.to_datetime(pd.Series(dates)).dt.normalize().to_numpy().astype("datetime64[D]")
    n_rows = len(bids)
    assays = np.full(n_rows, "culture", dtype=object)

    bd = beach_day.sort_values(["beach_id", "sample_date"])
    by_beach = {b: grp for b, grp in bd.groupby("beach_id", sort=False)}
    order = pd.Series(np.arange(n_rows)).groupby(bids)

    for b, idx in order:
        grp = by_beach.get(b)
        if grp is None:
            continue
        idx = idx.to_numpy()
        d = pd.to_datetime(grp["sample_date"]).dt.normalize().to_numpy().astype("datetime64[D]")
        m = grp["label_method"].to_numpy()
        q = qd[idx]
        h = np.searchsorted(d, q, "left")
        has = h > 0
        last = np.where(has, h - 1, 0)
        assays[idx] = np.where(has, m[last], "culture")
    return assays
