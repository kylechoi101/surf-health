"""Canonical sample key and physical-duplicate collapse for observations."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.data.pipeline.exceedance import is_pcr_measurement

CANONICAL_KEY = ["beach_id", "sample_day", "analyte", "assay_kind"]

_SOURCE_PRIORITY: dict[str, int] = {
    "BeachWatch.Live": 5,
    "BeachWatch.SafeToSwim": 4,
    "BeachWatch": 3,
    "CEDEN.SafeToSwim": 2,
    "CountyDirect": 1,
}


def assay_kind(method: pd.Series, units: pd.Series) -> pd.Series:
    """Classify measurements as molecular ('ddpcr') or culture ('culture').

    Delegates strictly to :func:`is_pcr_measurement` to avoid duplicating PCR logic.
    """
    pcr = is_pcr_measurement(method, units)
    return pd.Series(
        np.where(pcr.to_numpy(), "ddpcr", "culture"),
        index=pcr.index,
    )


def with_canonical_key(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of *df* with canonical grouping columns added.

    - ``sample_day``: normalized date (midnight) derived from ``sample_time``,
      falling back to ``sample_date`` when ``sample_time`` is null.
    - ``assay_kind``: 'ddpcr' or 'culture' based on method/units.
    """
    res = df.copy()
    if "sample_time" in res.columns:
        st = pd.to_datetime(res["sample_time"])
        if "sample_date" in res.columns:
            st = st.fillna(pd.to_datetime(res["sample_date"]))
    elif "sample_date" in res.columns:
        st = pd.to_datetime(res["sample_date"])
    else:
        st = pd.Series(pd.NaT, index=res.index)
    res["sample_day"] = st.dt.normalize()

    method_col = res["method"] if "method" in res.columns else pd.Series("", index=res.index)
    units_col = res["units"] if "units" in res.columns else pd.Series("", index=res.index)
    res["assay_kind"] = assay_kind(method_col, units_col)
    return res


def rebind_by_station_code(
    observations: pd.DataFrame, stations: pd.DataFrame
) -> pd.DataFrame:
    """Re-bind rows whose station_code names a different beach than their beach_id.

    Builds {(county_clean, normalized station_code) -> beach_id} from stations
    (columns beach_id, county, station_code; normalized with .str.strip().str.upper();
    keys mapping to >1 beach_id are dropped).
    """
    if observations.empty:
        print("[sample-key] re-bound 0 rows to their station_code's beach (by source: none)")
        return observations.copy()

    required_obs_cols = {"beach_id", "county", "station_code"}
    required_stn_cols = {"beach_id", "county", "station_code"}
    if not required_obs_cols.issubset(observations.columns) or not required_stn_cols.issubset(stations.columns):
        print("[sample-key] re-bound 0 rows to their station_code's beach (by source: none)")
        return observations.copy()

    st = stations.dropna(subset=["beach_id", "county", "station_code"]).copy()
    c_st = st["county"].astype(str).str.strip().str.upper()
    sc_st = st["station_code"].astype(str).str.strip().str.upper()
    valid_st_mask = (c_st != "") & (sc_st != "")
    st = st.loc[valid_st_mask].copy()
    st["_county_norm"] = c_st[valid_st_mask]
    st["_sc_norm"] = sc_st[valid_st_mask]

    counts = st.groupby(["_county_norm", "_sc_norm"])["beach_id"].nunique()
    unique_keys = counts[counts == 1].index
    mapping = (
        st.set_index(["_county_norm", "_sc_norm"])
        .loc[unique_keys]
        .groupby(level=[0, 1])["beach_id"]
        .first()
        .to_dict()
    )

    res = observations.copy()
    has_sc = res["station_code"].notna()
    has_c = res["county"].notna()
    c_obs = res["county"].astype(str).str.strip().str.upper()
    sc_obs = res["station_code"].astype(str).str.strip().str.upper()

    mapped_beach_ids = [
        mapping.get((c, sc)) if (hc and hs and c != "" and sc != "") else None
        for c, sc, hc, hs in zip(c_obs, sc_obs, has_c, has_sc, strict=False)
    ]
    rebound_mask = [
        m is not None and m != b for m, b in zip(mapped_beach_ids, res["beach_id"], strict=False)
    ]

    n_rebound = sum(rebound_mask)
    if n_rebound > 0:
        rebound_indices = [i for i, r in enumerate(rebound_mask) if r]
        new_bids = [mapped_beach_ids[i] for i in rebound_indices]
        res.loc[res.index[rebound_indices], "beach_id"] = new_bids

        if "data_source" in res.columns:
            sources = res["data_source"].iloc[rebound_indices].fillna("BeachWatch").replace("", "BeachWatch")
            counts_src = sources.value_counts()
            breakdown = ", ".join(f"{k}: {v}" for k, v in counts_src.items())
        else:
            breakdown = f"unknown: {n_rebound}"
    else:
        breakdown = "none"

    print(f"[sample-key] re-bound {n_rebound} rows to their station_code's beach (by source: {breakdown})")
    return res


def _val_close(v1: float, v2: float) -> bool:
    if np.isnan(v1) and np.isnan(v2):
        return True
    if np.isnan(v1) or np.isnan(v2):
        return False
    return bool(np.isclose(v1, v2))


def collapse_physical_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Keeps one row per physical sample across data sources.

    Within each (beach_id, sample_day, analyte, assay_kind) group:
    - Rows are distinct samples only if both have real collection times
      (not 00:00:00) and are >30 min apart.
    - Date-only rows join the cluster of the best-priority timed row,
      or form their own cluster if no timed row exists.
    - Two rows in one cluster are the same physical sample only if (a) their
      values are equal (np.isclose), OR (b) they come from DIFFERENT sources
      (a cross-source mirror, where a different value is a revision and source
      priority picks the winner). Two rows from the SAME source with different
      values are separate samples and both survive.
    - Winner within a merged sample: a row with a real collection time beats a
      date-only row; then source priority (BeachWatch.Live > BeachWatch.SafeToSwim
      > BeachWatch > CEDEN.SafeToSwim > CountyDirect), then worst sample
      (exceeds_stv, value, sample_time).
    """
    if df.empty:
        print("[sample-key] collapsed 0 physical-duplicate rows (by source: none)")
        res = df.copy()
        if "merged_from" not in res.columns:
            res["merged_from"] = pd.Series(dtype=str)
        return res

    keyed = with_canonical_key(df)
    st = (
        pd.to_datetime(keyed["sample_time"])
        if "sample_time" in keyed.columns
        else pd.Series(pd.NaT, index=keyed.index)
    )
    is_timed = st.notna() & (st != st.dt.normalize())

    if "data_source" in keyed.columns:
        source_clean = keyed["data_source"].fillna("BeachWatch")
        source_clean = source_clean.replace("", "BeachWatch")
    else:
        source_clean = pd.Series("BeachWatch", index=keyed.index)

    source_prio = source_clean.map(lambda s: _SOURCE_PRIORITY.get(s, 0)).to_numpy(dtype=int)

    if "exceeds_stv" in keyed.columns:
        exceed_rank = keyed["exceeds_stv"].fillna(False).astype(bool).astype(int).to_numpy()
    else:
        exceed_rank = np.zeros(len(keyed), dtype=int)

    if "value" in keyed.columns:
        raw_numeric = pd.to_numeric(keyed["value"], errors="coerce")
        value_rank = raw_numeric.fillna(float("-inf")).to_numpy()
        val_float = raw_numeric.to_numpy(dtype=float)
    else:
        value_rank = np.full(len(keyed), float("-inf"))
        val_float = np.full(len(keyed), np.nan)

    time_rank = st.fillna(pd.Timestamp.min).to_numpy()

    keyed["_is_timed"] = is_timed.to_numpy()
    keyed["_source_prio"] = source_prio
    keyed["_exceed_rank"] = exceed_rank
    keyed["_value_rank"] = value_rank
    keyed["_time_rank"] = time_rank
    keyed["_source_clean"] = source_clean.to_numpy()
    keyed["_orig_pos"] = np.arange(len(df))
    keyed["_val_float"] = val_float

    sizes = keyed.groupby(CANONICAL_KEY, sort=False)["beach_id"].transform("size")
    singles_mask = (sizes == 1).to_numpy()

    winner_indices: list[int] = []
    winner_merged: list[str] = []

    if np.any(singles_mask):
        singles_pos = keyed["_orig_pos"].to_numpy()[singles_mask]
        singles_src = keyed["_source_clean"].to_numpy()[singles_mask]
        winner_indices.extend(singles_pos)
        winner_merged.extend(singles_src)

    if not np.all(singles_mask):
        multis = keyed[~singles_mask]
        grouped = multis.groupby(CANONICAL_KEY, sort=False)

        def _row_key(r: tuple) -> tuple:
            return (r[0], r[1], r[2], r[3], r[4])

        for _, group in grouped:
            records = list(
                zip(
                    group["_is_timed"],
                    group["_source_prio"],
                    group["_exceed_rank"],
                    group["_value_rank"],
                    group["_time_rank"],
                    group["_source_clean"],
                    group["_orig_pos"],
                    group["_val_float"],
                    strict=False,
                )
            )
            timed = [r for r in records if r[0]]
            date_only = [r for r in records if not r[0]]

            if not timed:
                clusters = [date_only]
            else:
                timed.sort(key=lambda r: r[4])
                clusters = [[timed[0]]]
                for r in timed[1:]:
                    if r[4] - clusters[-1][-1][4] > pd.Timedelta(minutes=30):
                        clusters.append([r])
                    else:
                        clusters[-1].append(r)

                best_timed = max(timed, key=_row_key)
                for c in clusters:
                    if any(r[6] == best_timed[6] for r in c):
                        c.extend(date_only)
                        break

            for c in clusters:
                # Sub-cluster by (_source_clean, value)
                sub_clusters: list[dict[str, Any]] = []
                for r in c:
                    src = r[5]
                    val = r[7]
                    placed = False
                    for sc in sub_clusters:
                        if sc["source"] == src and _val_close(sc["val"], val):
                            sc["rows"].append(r)
                            placed = True
                            break
                    if not placed:
                        sub_clusters.append({"source": src, "val": val, "rows": [r]})

                for sc in sub_clusters:
                    sc["best_row"] = max(sc["rows"], key=_row_key)
                    sc["key"] = _row_key(sc["best_row"])

                sub_clusters.sort(key=lambda sc: sc["key"], reverse=True)

                merged_units: list[dict[str, Any]] = []
                unmatched: list[dict[str, Any]] = []

                # Pass 1: merge sub-clusters with matching values across sources
                for sc in sub_clusters:
                    matched_unit = None
                    for mu in merged_units:
                        if sc["source"] not in mu["sources"] and _val_close(mu["val"], sc["val"]):
                            matched_unit = mu
                            break
                    if matched_unit is not None:
                        matched_unit["sources"].add(sc["source"])
                        matched_unit["all_rows"].extend(sc["rows"])
                        if sc["key"] > _row_key(matched_unit["best_row"]):
                            matched_unit["best_row"] = sc["best_row"]
                    else:
                        unmatched.append(sc)

                # Pass 2: remaining unmatched sub-clusters merge across sources (cross-source revisions)
                for sc in unmatched:
                    merged_into = None
                    for mu in merged_units:
                        if sc["source"] not in mu["sources"]:
                            merged_into = mu
                            break
                    if merged_into is not None:
                        merged_into["sources"].add(sc["source"])
                        merged_into["all_rows"].extend(sc["rows"])
                        if sc["key"] > _row_key(merged_into["best_row"]):
                            merged_into["best_row"] = sc["best_row"]
                    else:
                        merged_units.append({
                            "val": sc["val"],
                            "sources": {sc["source"]},
                            "best_row": sc["best_row"],
                            "all_rows": list(sc["rows"]),
                        })

                for mu in merged_units:
                    winner_indices.append(mu["best_row"][6])
                    sources_str = ";".join(sorted(mu["sources"]))
                    winner_merged.append(sources_str)

    n_collapsed = len(df) - len(winner_indices)
    if n_collapsed > 0:
        kept_set = set(winner_indices)
        dropped_pos = [i for i in range(len(df)) if i not in kept_set]
        dropped_sources = source_clean.iloc[dropped_pos].value_counts()
        breakdown = ", ".join(f"{k}: {v}" for k, v in dropped_sources.items())
    else:
        breakdown = "none"

    print(f"[sample-key] collapsed {n_collapsed} physical-duplicate rows (by source: {breakdown})")

    result = df.iloc[winner_indices].copy()
    result["merged_from"] = winner_merged

    sort_cols = [c for c in ["beach_id", "sample_time"] if c in result.columns]
    if sort_cols:
        result = result.sort_values(sort_cols, kind="stable").reset_index(drop=True)
    else:
        result = result.reset_index(drop=True)

    return result
