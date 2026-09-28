"""Logistic challenger to the per-beach lookup (``lookup_serving``).

The served lookup knows WHICH beaches are dirty but has no day-to-day skill: its
within-beach AUROC is ~0.48. This model keeps the lookup as a fixed offset and
learns only the departures from it, from four terms known by 5 AM on day D:

    logit(p) = logit(lookup) + b0 + b1*R + b2*R*F + b3*W + b4*S

    R  log10(last lab result / its own limit), strictly before D, within the
       lookup window. Culture (104 MPN) and ddPCR (1413 copies) rows are put on
       one scale by ``enterococcus_action_ratio``; the raw value is method-blind.
    F  freshness of that result, exp(-(age_days - 1) / 3): 1.0 at 1 day,
       0.51 at 3 days, 0.14 at 7. A plain age term fit to ~0; age only matters
       through how much it discounts R.
    W  log2(1 + 4 * inches of rain in the 72h to 5 AM on D): 0 / 1 / 2 / 3 at
       0 / 0.25 / 0.75 / 1.75 in. Each step roughly doubles the odds.
    S  cos(season), +1 mid-January, -1 mid-July.

Every feature is computed as of D from rows strictly before D, the same rule as
``compute_lookup``, and every input is a curated artifact the daily-forecast
workflow already writes (``load_inputs``). Nothing here is wired into serving:
``python -m app.ml.logit_challenger --curated ../data/curated/`` writes a shadow
``challenger_forecasts.parquet`` beside ``forecasts.parquet``, and
``scripts/compare_logit_challenger.py`` scores it against the lookup.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.geo import haversine_km
from app.core.json_safe import dumps_strict
from app.ml.calibration import _LOW_THRESHOLD, advisory_floored_probability, risk_band
from app.ml.lookup_serving import posted_beach_ids_for

LOGIT_CHALLENGER_VERSION = "logit-lookup-offset-v1"
FEATURE_COLUMNS: tuple[str, ...] = ("R", "RF", "W", "S")

WINDOW_DAYS = 365
PRIOR_STRENGTH = 5.0
FRESHNESS_TAU_DAYS = 3.0
R_CLIP = 0.01  # results at <=1% of the limit all read as "very clean"
# No in-window result: a typical clean result (~a tenth of the limit, the median
# non-exceeding ratio), with F = 0 so it carries no freshness weight.
R_MISSING = -1.0


@dataclass(frozen=True)
class ChallengerInputs:
    """The daily workflow's own curated artifacts — the challenger reads nothing else."""

    beach_day: pd.DataFrame
    precip_daily: pd.DataFrame
    station_map: dict[str, str]


def load_inputs(curated_dir: Path | str) -> ChallengerInputs:
    """Read what ``app.data.pipeline.cli`` wrote in the daily-forecast workflow.

    beach_day.parquet            labels, enterococcus_action_ratio, beach coords
    precip_daily.parquet         rain windows per grid station, through the forecast date
    hydrologic_beach_links.parquet  pour points for the beach -> station rule
    """
    curated = Path(curated_dir)
    beach_day = pd.read_parquet(curated / "beach_day.parquet")
    precip_daily = pd.read_parquet(curated / "precip_daily.parquet")
    links_path = curated / "hydrologic_beach_links.parquet"
    links = pd.read_parquet(links_path) if links_path.exists() else None
    coords = (
        beach_day.dropna(subset=["latitude", "longitude"])
        .drop_duplicates("beach_id")
        .set_index("beach_id")[["latitude", "longitude"]]
    )
    beach_coords = {str(b): (float(r.latitude), float(r.longitude)) for b, r in coords.iterrows()}
    return ChallengerInputs(beach_day, precip_daily, precip_station_map(precip_daily, links, beach_coords))


def _dates(values) -> np.ndarray:
    # Explicit astype: pandas can hand back datetime64[s] even when asked for [D],
    # which silently turns every day difference below into seconds.
    return pd.to_datetime(pd.Series(values)).dt.normalize().to_numpy().astype("datetime64[D]")


def lab_history_features(
    beach_day: pd.DataFrame,
    beach_ids: Sequence[str],
    dates: Sequence,
    window_days: int = WINDOW_DAYS,
    prior_strength: float = PRIOR_STRENGTH,
) -> pd.DataFrame:
    """Lookup + last-result features for each (beach_id, date), strictly before date.

    ``lookup`` reproduces ``lookup_serving.compute_lookup``'s ``p_lookup``: the
    beach's exceedance rate over [date - window, date), shrunk toward the pooled
    rate of every beach over the same window.
    """
    bids = np.asarray(list(beach_ids), dtype=object)
    qd = _dates(dates)
    n_rows = len(bids)

    obs = beach_day.loc[beach_day["exceeds_stv"].notna()].copy()
    obs["_d"] = _dates(obs["sample_date"])
    obs["_y"] = obs["exceeds_stv"].astype(bool).astype(float)
    if "enterococcus_action_ratio" in obs.columns:
        ratio = pd.to_numeric(obs["enterococcus_action_ratio"], errors="coerce")
    else:
        ratio = pd.Series(np.nan, index=obs.index)
    obs["_r"] = np.log10(ratio.clip(lower=R_CLIP))
    # Same-day duplicates: the worst sample is the day's label (beach_day already
    # collapses to one row per beach-day; this keeps the order deterministic).
    obs = obs.sort_values(["beach_id", "_d", "_y", "_r"], na_position="first")

    window = np.timedelta64(window_days, "D")

    # Pooled rate g over [d - window, d) for every distinct query date.
    all_d = np.sort(obs["_d"].to_numpy())
    cum_y = np.concatenate([[0.0], np.cumsum(obs.sort_values("_d")["_y"].to_numpy())])
    uniq = np.unique(qd)
    hi = np.searchsorted(all_d, uniq, "left")
    lo = np.searchsorted(all_d, uniq - window, "left")
    cnt = hi - lo
    g_by_date = dict(zip(uniq, np.where(cnt > 0, (cum_y[hi] - cum_y[lo]) / np.maximum(cnt, 1), 0.0)))
    g = np.array([g_by_date[d] for d in qd])

    n = np.zeros(n_rows)
    pos = np.zeros(n_rows)
    last_r = np.full(n_rows, np.nan)
    last_y = np.full(n_rows, np.nan)
    age = np.full(n_rows, np.nan)

    order = pd.Series(np.arange(n_rows)).groupby(bids)
    by_beach = {b: grp for b, grp in obs.groupby("beach_id", sort=False)}
    for b, idx in order:
        grp = by_beach.get(b)
        if grp is None:
            continue
        idx = idx.to_numpy()
        d = grp["_d"].to_numpy()
        y = grp["_y"].to_numpy()
        r = grp["_r"].to_numpy()
        cy = np.concatenate([[0.0], np.cumsum(y)])
        q = qd[idx]
        h = np.searchsorted(d, q, "left")
        lo_b = np.searchsorted(d, q - window, "left")
        n[idx] = h - lo_b
        pos[idx] = cy[h] - cy[lo_b]
        has = h > lo_b
        last = np.where(has, h - 1, 0)
        last_r[idx] = np.where(has, r[last], np.nan)
        last_y[idx] = np.where(has, y[last], np.nan)
        age[idx] = np.where(has, (q - d[last]) / np.timedelta64(1, "D"), np.nan)

    lookup = (pos + prior_strength * g) / (n + prior_strength)
    lookup_c = np.clip(lookup, 1e-4, 1 - 1e-4)
    freshness = np.where(np.isnan(age), 0.0, np.exp(-(np.nan_to_num(age, nan=1.0) - 1.0) / FRESHNESS_TAU_DAYS))
    r_feat = np.where(np.isnan(last_r), R_MISSING, last_r)

    return pd.DataFrame(
        {
            "beach_id": bids,
            "date": pd.to_datetime(qd),
            "n": n.astype(int),
            "pos": pos.astype(int),
            "g": g,
            "lookup": lookup,
            "L": np.log(lookup_c / (1 - lookup_c)),
            "last_exceeds": last_y,
            "last_log10_ratio": last_r,
            "age_days": age,
            "R": r_feat,
            "F": freshness,
        }
    )


def precip_station_map(
    precip_daily: pd.DataFrame,
    hydrologic_links: pd.DataFrame | None,
    beach_coords: Mapping[str, tuple[float, float]],
) -> dict[str, str]:
    """beach_id -> precip_daily station_id, by the pipeline's own rule.

    Same rule as ``hydrology.build_beach_hydrology_daily`` (which built beach_day's
    precip columns) and ``training._candidate_nearest_precip_station`` (which
    refreshes them at forecast time): nearest station by haversine to the beach's
    hydrologic pour point, falling back to the beach's own lat/lon.
    """
    stations = (
        precip_daily[["station_id", "latitude", "longitude"]]
        .dropna(subset=["latitude", "longitude"])
        .drop_duplicates("station_id")
    )
    if stations.empty:
        return {}
    points: dict[str, tuple[float, float]] = {}
    if hydrologic_links is not None and not hydrologic_links.empty:
        pour = hydrologic_links.dropna(subset=["pour_point_latitude", "pour_point_longitude"])
        for row in pour.drop_duplicates("beach_id").itertuples(index=False):
            points[str(row.beach_id)] = (row.pour_point_latitude, row.pour_point_longitude)
    for bid, latlon in beach_coords.items():
        points.setdefault(str(bid), latlon)
    st_ids = stations["station_id"].astype(str).tolist()
    st = list(zip(stations["latitude"].astype(float), stations["longitude"].astype(float)))
    mapping = {}
    for bid, (lat, lon) in points.items():
        d = [haversine_km(float(lat), float(lon), slat, slon) for slat, slon in st]
        mapping[bid] = st_ids[int(np.argmin(d))]
    return mapping


def rain_feature(
    precip_daily: pd.DataFrame,
    station_map: Mapping[str, str],
    beach_ids: Sequence[str],
    dates: Sequence,
) -> np.ndarray:
    """W = log2(1 + 4 * inches of rain in the 72h to 5 AM on date). Missing -> 0 (dry)."""
    pr = precip_daily[["station_id", "sample_date", "precip_mm_72h"]].copy()
    pr["station_id"] = pr["station_id"].astype(str)
    pr["sample_date"] = pd.to_datetime(pr["sample_date"]).dt.normalize()
    pr = pr.drop_duplicates(["station_id", "sample_date"], keep="last")
    s = pr.set_index(["station_id", "sample_date"])["precip_mm_72h"]
    keys = [station_map.get(str(b)) for b in beach_ids]
    idx = pd.MultiIndex.from_arrays([keys, pd.to_datetime(pd.Series(dates)).dt.normalize()])
    mm = s.reindex(idx).to_numpy(dtype=float)
    inches = np.nan_to_num(mm, nan=0.0).clip(min=0.0) / 25.4
    return np.log2(1.0 + 4.0 * inches)


def season_feature(dates: Sequence) -> np.ndarray:
    doy = pd.to_datetime(pd.Series(dates)).dt.dayofyear.to_numpy()
    return np.cos(2 * np.pi * (doy - 15) / 365.25)


def build_features(
    inputs: ChallengerInputs, beach_ids: Sequence[str], dates: Sequence
) -> pd.DataFrame:
    feats = lab_history_features(inputs.beach_day, beach_ids, dates)
    feats["W"] = rain_feature(inputs.precip_daily, inputs.station_map, beach_ids, dates)
    feats["S"] = season_feature(dates)
    feats["RF"] = feats["R"] * feats["F"]
    return feats


def fit_coefficients(
    features: pd.DataFrame, y: Sequence, ridge: float = 1e-4, max_iter: int = 50
) -> dict[str, float]:
    """Logistic regression with ``L`` as a fixed offset (Newton / IRLS)."""
    X = np.column_stack([np.ones(len(features))] + [features[c].to_numpy(float) for c in FEATURE_COLUMNS])
    off = features["L"].to_numpy(float)
    yy = np.asarray(y, dtype=float)
    beta = np.zeros(X.shape[1])
    penalty = ridge * np.eye(X.shape[1])
    penalty[0, 0] = 0.0
    for _ in range(max_iter):
        p = 1.0 / (1.0 + np.exp(-(off + X @ beta)))
        w = p * (1 - p)
        grad = X.T @ (yy - p) - penalty @ beta
        hess = (X * w[:, None]).T @ X + penalty
        step = np.linalg.solve(hess, grad)
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return dict(zip(("intercept",) + FEATURE_COLUMNS, map(float, beta)))


def predict(features: pd.DataFrame, coefs: Mapping[str, float]) -> np.ndarray:
    eta = features["L"].to_numpy(float) + coefs["intercept"]
    for c in FEATURE_COLUMNS:
        eta = eta + coefs[c] * features[c].to_numpy(float)
    return 1.0 / (1.0 + np.exp(-eta))


def apply_persistence_floor(p: np.ndarray, last_exceeds: np.ndarray) -> np.ndarray:
    """The product rule both serving paths share: last sample exceeded -> never Low."""
    p = np.asarray(p, dtype=float)
    return np.where(np.asarray(last_exceeds) == 1, np.maximum(p, _LOW_THRESHOLD), p)


def fit_on_history(
    inputs: ChallengerInputs,
    forecast_date: str | pd.Timestamp,
    train_years: int = 4,
) -> tuple[dict[str, float], int]:
    """Fit on every sample-day in [D - train_years, D), features as of each sample's own date."""
    d = pd.Timestamp(forecast_date).normalize()
    bd = inputs.beach_day
    dates = pd.to_datetime(bd["sample_date"]).dt.normalize()
    start = max(d - pd.DateOffset(years=train_years), pd.to_datetime(inputs.precip_daily["sample_date"]).min())
    rows = bd.loc[(dates >= start) & (dates < d) & bd["exceeds_stv"].notna()]
    feats = build_features(inputs, rows["beach_id"].tolist(), pd.to_datetime(rows["sample_date"]).tolist())
    return fit_coefficients(feats, rows["exceeds_stv"].astype(int).to_numpy()), len(rows)


def score_forecast_date(curated_dir: Path | str) -> dict:
    """Shadow-score every beach in forecasts.parquet for its forecast date.

    Writes ``challenger_forecasts.parquet``; never touches the served artifacts.
    """
    curated = Path(curated_dir)
    forecasts = pd.read_parquet(curated / "forecasts.parquet")
    d = pd.Timestamp(forecasts["forecast_date"].iloc[0]).normalize()
    inputs = load_inputs(curated)
    coefs, n_train = fit_on_history(inputs, d)
    beach_ids = forecasts["beach_id"].astype(str).tolist()
    feats = build_features(inputs, beach_ids, [d] * len(beach_ids))
    p_raw = predict(feats, coefs)
    p = apply_persistence_floor(p_raw, feats["last_exceeds"].to_numpy())
    # Same posted-beach set the served lookup floors (lookup_serving), so the two
    # differ only in the model, never in the product rules layered on top.
    posted = posted_beach_ids_for(curated, d)
    is_posted = np.array([b in posted for b in beach_ids])
    p = np.array([advisory_floored_probability(x, bool(f))[0] for x, f in zip(p, is_posted)])
    out = feats[["beach_id", "lookup", "R", "F", "W", "S", "age_days", "last_exceeds"]].copy()
    out.insert(1, "forecast_date", d.date())
    out["advisory_posted"] = is_posted
    out["p_exceed_challenger_raw"] = p_raw
    out["p_exceed_challenger"] = p
    out["risk_band_challenger"] = [risk_band(x) for x in p]
    out["p_exceed_served"] = forecasts["p_exceed"].to_numpy()
    out["model_version"] = LOGIT_CHALLENGER_VERSION
    path = curated / "challenger_forecasts.parquet"
    tmp = path.with_suffix(".parquet.tmp")
    out.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return {
        "model": LOGIT_CHALLENGER_VERSION,
        "forecast_date": str(d.date()),
        "rows": len(out),
        "train_rows": n_train,
        "coefficients": coefs,
        "rain_rows": int((out["W"] > 0).sum()),
        "posted": int(is_posted.sum()),
        "bands": out["risk_band_challenger"].value_counts().to_dict(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Shadow-score the logistic challenger")
    parser.add_argument("--curated", type=Path, required=True, help="Path to curated data directory")
    args = parser.parse_args()
    print(dumps_strict(score_forecast_date(args.curated)))


if __name__ == "__main__":
    main()
