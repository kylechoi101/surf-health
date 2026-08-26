#!/usr/bin/env python
"""Refit the serving isotonic with sampling-frequency weights, and report what
changes in the served risk bands.

Why
---
``fit_serving_calibration`` fits on served rows that later got a lab outcome.
That is ~5% of served rows and it is NOT a random 5%: a beach enters the fit set
once per lab visit, so beaches sampled twice a week outweigh beaches sampled
monthly by ~8x, and the frequently-sampled cohort is overwhelmingly San Diego
ddPCR (measured base rate 0.593 vs 0.100 for culture rows). An isotonic maps
p -> observed frequency IN ITS FIT SET, so a fit population enriched in
positives is then applied wholesale to a served population that is not.

This is selection bias, not leakage: every pair is honestly out-of-sample in
time. The fix is post-stratification -- reweight each fit row so that each
beach contributes in proportion to its share of the SERVED population rather
than its share of the SAMPLED population.

    w_b = (served_rows_b / served_rows_total) / (fit_rows_b / fit_rows_total)

Diagnostic only. Writes no production artifact; prints the band-count delta a
production switch would cause and the residual bias weighting CANNOT fix
(served beaches with zero fit rows are unrepresented at any weight).

Run (from backend/):  python -m scripts.reweight_serving_calibration
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "backend"))

from app.ml.calibration import (  # noqa: E402
    _HIGH_THRESHOLD,
    _LOW_THRESHOLD,
    _VERY_HIGH_THRESHOLD,
)
from app.ml.served_metrics import (  # noqa: E402
    _FIT_WINDOW_DAYS,
    _MIN_TOP_STEP_SUPPORT,
    _cap_undersupported_top_step,
    _drop_pin_era_rows,
    _matched_from_disk,
)

CURATED = _REPO / "data" / "curated"
OUT_JSON = _REPO / "data" / "experiments" / "serving_calibration_reweight.json"
BANDS = ("Low", "Moderate", "High", "Very High")


def band_of(p: np.ndarray) -> np.ndarray:
    return np.select(
        [p < _LOW_THRESHOLD, p < _HIGH_THRESHOLD, p < _VERY_HIGH_THRESHOLD],
        ["Low", "Moderate", "High"],
        default="Very High",
    )


def fit_isotonic(x: np.ndarray, y: np.ndarray, w: np.ndarray | None) -> dict:
    """Production's fit, plus an optional sample_weight. Same top-step cap."""
    model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    model.fit(x, y, sample_weight=w)
    knots_y, y_cap, capped_from = _cap_undersupported_top_step(
        np.asarray(model.X_thresholds_, dtype=float),
        np.asarray(model.y_thresholds_, dtype=float),
        x,
    )
    return {
        "x": np.asarray(model.X_thresholds_, dtype=float),
        "y": np.asarray(knots_y, dtype=float),
        "y_max": float(y_cap),
        "top_step_capped_from": capped_from,
    }


def apply_map(p: np.ndarray, m: dict) -> np.ndarray:
    return np.clip(np.interp(p, m["x"], m["y"]), 0.0, 1.0)


def main() -> int:
    loaded = _matched_from_disk(CURATED)
    if loaded is None:
        print("no matched history on disk", file=sys.stderr)
        return 1
    matched = loaded[0]

    pairs = matched.dropna(subset=["p_fit", "outcome_matched"])
    latest = pairs["date"].max()
    window_start = latest - pd.Timedelta(days=_FIT_WINDOW_DAYS)
    pairs = pairs[pairs["date"] > window_start]
    pairs = _drop_pin_era_rows(pairs).copy()

    # Served population over the SAME window: every row we published, whether or
    # not a lab ever visited. This is the population the map is applied to.
    history = pd.read_parquet(
        CURATED / "forecast_history.parquet",
        columns=["beach_id", "forecast_date"],
    )
    history["date"] = pd.to_datetime(history["forecast_date"], errors="coerce").dt.normalize()
    served = history[(history["date"] > window_start) & (history["date"] <= latest)]

    served_counts = served.groupby("beach_id").size()
    fit_counts = pairs.groupby("beach_id").size()

    served_share = served_counts / served_counts.sum()
    fit_share = fit_counts / fit_counts.sum()
    weight_by_beach = (served_share.reindex(fit_share.index) / fit_share).fillna(0.0)

    x = pairs["p_fit"].astype(float).to_numpy()
    y = pairs["outcome_matched"].astype(int).to_numpy()
    w = pairs["beach_id"].map(weight_by_beach).astype(float).to_numpy()
    w = w * (len(w) / w.sum())  # normalise to mean 1 so n_eff is comparable

    unweighted = fit_isotonic(x, y, None)
    weighted = fit_isotonic(x, y, w)

    # Coverage: weighting cannot represent a beach with zero fit rows.
    served_beaches = set(served_counts.index)
    fit_beaches = set(fit_counts.index)
    uncovered = served_beaches - fit_beaches
    uncovered_share = float(served_counts.reindex(sorted(uncovered)).sum() / served_counts.sum())

    print("=" * 74)
    print("FIT POPULATION vs SERVED POPULATION")
    print("=" * 74)
    print(f"  window                 : {window_start.date()} .. {latest.date()} "
          f"({_FIT_WINDOW_DAYS}d)")
    print(f"  fit pairs              : {len(pairs):>7,}  over {len(fit_beaches):>4} beaches")
    print(f"  served rows            : {len(served):>7,}  over {len(served_beaches):>4} beaches")
    print(f"  verifiable fraction    : {len(pairs) / max(len(served), 1):>7.3%}")
    print(f"  fit base rate          : {y.mean():>7.4f}")
    print(f"  effective n after wts  : {w.sum() ** 2 / (w ** 2).sum():>7,.0f}")
    print(f"  weight range           : {w.min():.3f} .. {w.max():.3f}")
    print(f"  served beaches with NO fit row : {len(uncovered):>4} "
          f"({uncovered_share:.1%} of served rows)  <- weighting cannot fix these")

    print()
    print("=" * 74)
    print("MAP SHAPE")
    print("=" * 74)
    for name, m in (("unweighted (production)", unweighted), ("beach-reweighted", weighted)):
        cap = m["top_step_capped_from"]
        print(f"  {name:<26} knots {len(m['x']):>3}  ceiling {m['y_max']:.4f}"
              f"{'' if cap is None else f'  (capped from {cap:.4f})'}")

    # Scoring. The weighted Brier is the honest one: it asks how the map performs
    # on the population it is actually applied to, not on the sampled subset.
    print()
    print(f"  {'':<26}{'Brier (fit pop)':>17}{'Brier (served-wtd)':>21}")
    for name, p in (
        ("raw (no calibration)", x),
        ("unweighted map", apply_map(x, unweighted)),
        ("reweighted map", apply_map(x, weighted)),
    ):
        b_fit = brier_score_loss(y, p)
        b_wtd = float(np.average((p - y) ** 2, weights=w))
        print(f"  {name:<26}{b_fit:>17.4f}{b_wtd:>21.4f}")
    flat = float(np.average((y.mean() - y) ** 2, weights=w))
    print(f"  {'flat base-rate constant':<26}{np.mean((y.mean() - y) ** 2):>17.4f}{flat:>21.4f}")

    # Band counts on the live forecast.
    fc = pd.read_parquet(CURATED / "forecasts.parquet")
    precal = pd.to_numeric(fc["p_exceed_precal"], errors="coerce").to_numpy(dtype=float)
    floor = fc.get("persistence_floor_applied")
    floor_mask = (
        np.zeros(len(fc), dtype=bool) if floor is None
        else floor.fillna(False).astype(bool).to_numpy()
    )
    ok = ~np.isnan(precal)

    print()
    print("=" * 74)
    print(f"LIVE FORECAST BAND COUNTS  (forecast_date "
          f"{pd.to_datetime(fc['forecast_date']).max().date()}, n={int(ok.sum())})")
    print("=" * 74)
    table = {}
    for name, m in (("shipped (unweighted)", unweighted), ("reweighted", weighted)):
        p = apply_map(precal[ok], m)
        p = np.where(floor_mask[ok], np.maximum(p, _LOW_THRESHOLD), p)
        counts = pd.Series(band_of(p)).value_counts()
        table[name] = {b: int(counts.get(b, 0)) for b in BANDS}
        table[name]["mean_p"] = round(float(p.mean()), 4)
    hdr = f"  {'':<22}" + "".join(f"{b:>11}" for b in BANDS) + f"{'mean p':>10}"
    print(hdr)
    for name, row in table.items():
        print(f"  {name:<22}" + "".join(f"{row[b]:>11,}" for b in BANDS)
              + f"{row['mean_p']:>10.4f}")
    delta = {b: table["reweighted"][b] - table["shipped (unweighted)"][b] for b in BANDS}
    print(f"  {'delta':<22}" + "".join(f"{delta[b]:>+11,}" for b in BANDS)
          + f"{table['reweighted']['mean_p'] - table['shipped (unweighted)']['mean_p']:>+10.4f}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "window": {"start": str(window_start.date()), "end": str(latest.date()),
                   "days": _FIT_WINDOW_DAYS},
        "fit_pairs": len(pairs), "fit_beaches": len(fit_beaches),
        "served_rows": len(served), "served_beaches": len(served_beaches),
        "verifiable_fraction": round(len(pairs) / max(len(served), 1), 5),
        "fit_base_rate": round(float(y.mean()), 4),
        "uncovered_beaches": len(uncovered),
        "uncovered_served_share": round(uncovered_share, 4),
        "effective_n": round(float(w.sum() ** 2 / (w ** 2).sum()), 1),
        "min_top_step_support": int(_MIN_TOP_STEP_SUPPORT),
        "maps": {k: {"x": [round(v, 6) for v in m["x"].tolist()],
                     "y": [round(v, 6) for v in m["y"].tolist()],
                     "y_max": round(m["y_max"], 6)}
                 for k, m in (("unweighted", unweighted), ("reweighted", weighted))},
        "band_counts": table,
        "band_delta": delta,
    }, indent=2) + "\n")
    print(f"\nwrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
