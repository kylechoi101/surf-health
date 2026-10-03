"""Diff a standalone-built forecast against the one training produced (UPDATE_PLAN 3.4).

``lookup_serving --standalone`` rebuilds ``forecasts.parquet`` without the ML
training step. In shadow it runs beside the real pipeline and this script says
whether the two agree on the served numbers:

  * the same beach set;
  * ``p_exceed`` equal to 1e-9, and ``risk_band``, ``advisory_floor_applied``,
    ``persistence_floor_applied`` equal.

Columns outside that list are never reported. ``forecast_generated_at`` is
wall-clock and differs by construction; the ML-only columns (``p_exceed_ml``,
``risk_band_ml``, ``p_exceed_precal``, ``served_offset_weight``,
``predicted_log_enterococcus``, the prediction intervals) are null in the
standalone frame by design.

Shadow is informational: this always exits 0. ``--log`` appends one JSON record
(``date, rows_real, rows_shadow, beaches_equal, max_abs_dp, n_diff``) so a run of
daily verdicts can be committed with the data.

Usage:
  python scripts/diff_standalone_forecast.py --real DIR --shadow DIR [--log FILE --date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_FORECASTS_FILE = "forecasts.parquet"
P_TOLERANCE = 1e-9
EXACT_COLUMNS = ("risk_band", "advisory_floor_applied", "persistence_floor_applied")
MAX_ROWS_SHOWN = 20


def _same(a: pd.Series, b: pd.Series) -> pd.Series:
    """Element-wise equality where null == null."""
    return (a == b) | (a.isna() & b.isna())


def compare(real: pd.DataFrame, shadow: pd.DataFrame) -> dict:
    """Return the verdict record plus the differing rows (key ``rows``)."""
    real_ids = set(real["beach_id"])
    shadow_ids = set(shadow["beach_id"])
    beaches_equal = real_ids == shadow_ids
    both = sorted(real_ids & shadow_ids)

    r = real.drop_duplicates("beach_id").set_index("beach_id").reindex(both)
    s = shadow.drop_duplicates("beach_id").set_index("beach_id").reindex(both)

    def col(frame: pd.DataFrame, name: str) -> pd.Series:
        return frame[name] if name in frame.columns else pd.Series(np.nan, index=frame.index, dtype=object)

    pr = pd.to_numeric(col(r, "p_exceed"), errors="coerce")
    ps = pd.to_numeric(col(s, "p_exceed"), errors="coerce")
    dp = (pr - ps).abs()
    p_bad = ~(dp.fillna(0.0).le(P_TOLERANCE) & (pr.isna() == ps.isna()))
    bad = {"p_exceed": p_bad}
    for name in EXACT_COLUMNS:
        bad[name] = ~_same(col(r, name), col(s, name))

    any_bad = np.zeros(len(both), dtype=bool)
    for mask in bad.values():
        any_bad |= mask.to_numpy()

    rows = []
    for beach_id in np.asarray(both, dtype=object)[any_bad][:MAX_ROWS_SHOWN]:
        row = {"beach_id": beach_id}
        for name in ("p_exceed", *EXACT_COLUMNS):
            row[f"{name}_real"] = col(r, name).loc[beach_id]
            row[f"{name}_shadow"] = col(s, name).loc[beach_id]
        rows.append(row)

    return {
        "rows_real": int(len(real)),
        "rows_shadow": int(len(shadow)),
        "beaches_equal": bool(beaches_equal),
        "max_abs_dp": float(dp.max()) if dp.notna().any() else 0.0,
        "n_diff": int(any_bad.sum()),
        "missing_in_shadow": sorted(real_ids - shadow_ids)[:MAX_ROWS_SHOWN],
        "extra_in_shadow": sorted(shadow_ids - real_ids)[:MAX_ROWS_SHOWN],
        "rows": rows,
    }


def verdict_line(result: dict) -> str:
    ok = result["beaches_equal"] and result["n_diff"] == 0
    return (
        f"{'SHADOW MATCH' if ok else 'SHADOW DIFF'}: rows real={result['rows_real']} "
        f"shadow={result['rows_shadow']} beaches_equal={result['beaches_equal']} "
        f"n_diff={result['n_diff']} max_abs_dp={result['max_abs_dp']:.3g}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff standalone vs real forecasts (informational)")
    parser.add_argument("--real", type=Path, required=True)
    parser.add_argument("--shadow", type=Path, required=True)
    parser.add_argument("--log", type=Path, default=None, help="append a JSON verdict record here")
    parser.add_argument("--date", default=None, help="date stamped on the --log record")
    args = parser.parse_args()

    try:
        real = pd.read_parquet(args.real / _FORECASTS_FILE)
        shadow = pd.read_parquet(args.shadow / _FORECASTS_FILE)
    except Exception as exc:  # shadow must never fail the job
        print(f"SHADOW ERROR: cannot read forecasts: {exc}", file=sys.stderr)
        return 0

    result = compare(real, shadow)
    print(verdict_line(result))
    if result["missing_in_shadow"]:
        print(f"missing in shadow: {result['missing_in_shadow']}")
    if result["extra_in_shadow"]:
        print(f"extra in shadow: {result['extra_in_shadow']}")
    if result["rows"]:
        print(pd.DataFrame(result["rows"]).to_string(index=False))

    if args.log is not None:
        record = {
            "date": args.date,
            **{k: result[k] for k in ("rows_real", "rows_shadow", "beaches_equal", "max_abs_dp", "n_diff")},
        }
        with args.log.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
