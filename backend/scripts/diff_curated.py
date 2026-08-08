#!/usr/bin/env python
"""Diff two curated-artifact snapshots and report exactly what moved.

Every step of the rebuild programme ends by running this against the frozen
baseline from step 1, so a fix can be told apart from a regression. It answers
seven questions per snapshot pair:

1. **Schema deltas** — columns added / removed / dtype-changed, per file.
2. **Row-count deltas** — per file.
3. **Key-set deltas** — rows present on one side only, on that file's natural
   key.
4. **Label flips** — for ``beach_day.parquet``, rows whose ``exceeds_stv``
   changed, split by direction (0->1 vs 1->0; a fix and a regression are
   indistinguishable in a total) and broken down by county and, when the
   columns exist, by ``label_method`` / ``is_pcr``.
5. **Value deltas** — for ``enterococcus_value``, how many rows moved and by
   how much. The step-4 full rebuild re-runs the same-day worst-sample
   collapse, so value movement is expected there and has to be quantified
   apart from the assay change or the two get confounded.
6. **Feature coverage** — ``notna()`` fraction per column, before vs after,
   sorted by largest change. This is how the step-2 weather backfill is
   verified.
7. **Per-cell value changes** — for *every* shared column on the joined key,
   how many rows changed value, with a delta summary for numerics and the top
   value transitions for categoricals.

Question 7 exists because questions 4-6 have a hole between them.  Coverage is
a ``notna()`` fraction, not an equality check: a column can change value on
every single row and still report "coverage unchanged". Before this mode
existed the harness compared *values* on exactly two columns (``exceeds_stv``
and ``enterococcus_value``), so a value-only move in any of the other ~85
``beach_day`` columns was invisible. Step 4 hit this for real — 187 rows of
``advisory_active_prev_14d`` movement (107 ``0->1``, 80 ``1->0``, 23 beaches)
were reported as "unchanged" and had to be found with a separate ad-hoc pass.
Every step of the programme certifies itself with this tool, and a harness that
cannot see a change cannot certify that one did not happen.

Either side may be a snapshot directory (see :mod:`snapshot_curated`) or
``data/curated`` itself. A file missing from one side is reported, not fatal,
and the two sides are expected to have different schemas.

Usage::

    python scripts/diff_curated.py \
        --before ../data/baseline/2026-08-07 \
        --after  ../data/curated \
        --json /tmp/diff.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# Files compared, and the natural key used for row-level joins. An empty key
# means the file is compared on schema/rows/coverage only.
FILE_KEYS: dict[str, tuple[str, ...]] = {
    "beach_day.parquet": ("beach_id", "sample_date"),
    "observations.parquet": ("beach_id", "sample_time", "analyte", "method"),
    "beaches.parquet": ("beach_id",),
    "forecast_history.parquet": ("beach_id", "forecast_date", "forecast_generated_at"),
    "forecasts.parquet": ("beach_id", "forecast_date"),
}

JSON_FILES: tuple[str, ...] = (
    "system_health.json",
    "serving_calibration.json",
    "model_version.json",
    "production_model.json",
)

LABEL_COLUMN = "exceeds_stv"
VALUE_COLUMN = "enterococcus_value"
# Breakdown dimensions for label flips, used when present.
FLIP_BREAKDOWNS: tuple[str, ...] = ("county", "label_method", "is_pcr")

# Coverage moves below this (0.01 percentage points) are almost always just the
# row count changing under a constant numerator; override with
# --coverage-epsilon when a sub-0.01pp move is the thing being checked.
COVERAGE_EPSILON = 1e-4
# enterococcus_value moves smaller than this are float round-trip, not data.
VALUE_EPSILON = 1e-9
# Same idea for the per-cell sweep over every numeric column. Step 4 measured
# 9,876 rows of `dist_to_pier_km` "movement" under exact ==, every delta <=1e-9
# — parquet float round-trip, not data. Absolute, not relative: these columns
# are physical quantities in human units, none of them near float epsilon.
CELL_EPSILON = 1e-9
# Categorical columns report their most common before->after transitions; this
# is what turns "label_method changed on 1,642 rows" into "1,483 of them are
# EPA 1600 -> 1600, i.e. a spelling, not a relabel".
CELL_TRANSITIONS = 5


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _read(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_parquet(path)


def _key_series(frame: pd.DataFrame, key: tuple[str, ...]) -> pd.Series:
    """Stringified composite key, so joins survive dtype drift across sides."""
    parts = [frame[col].astype(str) for col in key]
    joined = parts[0]
    for part in parts[1:]:
        joined = joined + "\x1f" + part
    return joined


def _dedupe_on_key(frame: pd.DataFrame, key: tuple[str, ...]) -> tuple[pd.DataFrame, int]:
    """Index a frame by its natural key, dropping duplicate keys.

    Duplicates are reported rather than silently exploding the join into a
    cartesian product.
    """
    keys = _key_series(frame, key)
    dupes = int(keys.duplicated().sum())
    indexed = frame.copy()
    indexed.index = pd.Index(keys, name="_key")
    if dupes:
        indexed = indexed[~indexed.index.duplicated(keep="first")]
    return indexed, dupes


def _coverage(frame: pd.DataFrame) -> dict[str, tuple[float, int]]:
    """Per-column (notna fraction, notna count)."""
    total = len(frame)
    out: dict[str, tuple[float, int]] = {}
    for column in frame.columns:
        count = int(frame[column].notna().sum())
        out[str(column)] = ((count / total) if total else 0.0, count)
    return out


def _quantiles(series: pd.Series) -> dict[str, float | None]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return {}
    return {
        "min": float(clean.min()),
        "p05": float(clean.quantile(0.05)),
        "p25": float(clean.quantile(0.25)),
        "median": float(clean.median()),
        "p75": float(clean.quantile(0.75)),
        "p95": float(clean.quantile(0.95)),
        "max": float(clean.max()),
        "mean": float(clean.mean()),
    }


@dataclass(frozen=True)
class _Aligned:
    """The two sides restricted to their shared keys, in the same row order.

    Built once per file and reused by the label, value and cell comparisons —
    they all need the identical join, and doing it three times on a 492k x 87
    frame is the difference between a usable harness and one nobody runs.

    Rows are addressed positionally (``b_pos`` / ``a_pos``) rather than by
    ``.loc``: an index lookup per column is ~87 hash-joins over half a million
    keys, whereas ``take`` is a flat gather.
    """

    key: tuple[str, ...]
    before: pd.DataFrame
    after: pd.DataFrame
    b_pos: np.ndarray
    a_pos: np.ndarray
    shared: pd.Index
    dupes_before: int
    dupes_after: int

    def column_pair(self, column: str) -> tuple[pd.Series, pd.Series]:
        """The column from both sides, aligned row-for-row on the shared keys."""
        return (
            self.before[column].take(self.b_pos),
            self.after[column].take(self.a_pos),
        )


def _align(before: pd.DataFrame, after: pd.DataFrame, key: tuple[str, ...]) -> _Aligned | None:
    if any(c not in before.columns or c not in after.columns for c in key):
        return None
    b_idx, b_dupes = _dedupe_on_key(before, key)
    a_idx, a_dupes = _dedupe_on_key(after, key)
    shared = b_idx.index.intersection(a_idx.index)
    return _Aligned(
        key=key,
        before=b_idx,
        after=a_idx,
        b_pos=b_idx.index.get_indexer(shared),
        a_pos=a_idx.index.get_indexer(shared),
        shared=shared,
        dupes_before=b_dupes,
        dupes_after=a_dupes,
    )


def _is_numeric_like(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series.dtype) or pd.api.types.is_bool_dtype(series.dtype)


def _to_float_array(series: pd.Series) -> np.ndarray:
    """Float view of a numeric/bool/nullable column, NA -> nan."""
    if pd.api.types.is_bool_dtype(series.dtype):
        series = series.astype("boolean")
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.to_numpy(dtype="float64", na_value=np.nan)


NULL_LABEL = "<null>"


def _stringify(series: pd.Series) -> np.ndarray:
    """String view of a column with nulls rendered explicitly, never dropped."""
    return np.where(
        series.isna().to_numpy(dtype="bool"),
        NULL_LABEL,
        series.astype(str).to_numpy(dtype=object),
    )


def _not_equal_mask(b_series: pd.Series, a_series: pd.Series) -> np.ndarray:
    """Elementwise inequality for non-numeric columns, NA-involving -> True.

    NaN-vs-NaN is handled by the caller's ``both_na`` mask, so returning True
    here for any comparison involving a null is correct: null-vs-value *is* a
    change.
    """
    try:
        neq = b_series.ne(a_series)
    except (TypeError, ValueError):
        # Mismatched non-comparable dtypes across sides (e.g. object vs
        # datetime after a schema change). String form is the honest fallback.
        neq = b_series.astype(str).ne(a_series.astype(str))
    return neq.to_numpy(dtype="bool", na_value=True)


def _compare_cells(
    b_series: pd.Series,
    a_series: pd.Series,
    epsilon: float,
    max_transitions: int,
) -> dict:
    """Per-cell comparison of one column across the two aligned sides.

    NaN-vs-NaN is equal; NaN-vs-value is a change. Numeric columns get a delta
    distribution and a direction split; everything else gets its top
    before->after transitions.
    """
    b_na = b_series.isna().to_numpy(dtype="bool")
    a_na = a_series.isna().to_numpy(dtype="bool")
    both_na = b_na & a_na
    total = int(len(b_series))

    entry: dict = {
        "column": str(b_series.name),
        "rows": total,
        "became_null": int((~b_na & a_na).sum()),
        "became_present": int((b_na & ~a_na).sum()),
    }

    if _is_numeric_like(b_series) and _is_numeric_like(a_series):
        b_val = _to_float_array(b_series)
        a_val = _to_float_array(a_series)
        with np.errstate(invalid="ignore"):
            delta = a_val - b_val
            moved = np.abs(delta) > epsilon
        moved = np.where(np.isnan(delta), False, moved)
        changed = (~both_na) & (moved | (b_na ^ a_na))
        entry["kind"] = "numeric"
        entry["changed_rows"] = int(changed.sum())
        entry["increased"] = int((delta > epsilon).sum())
        entry["decreased"] = int((delta < -epsilon).sum())
        entry["delta_distribution"] = _quantiles(pd.Series(delta[moved]))
    else:
        neq = _not_equal_mask(b_series, a_series)
        changed = neq & ~both_na
        entry["kind"] = "categorical"
        entry["changed_rows"] = int(changed.sum())
        entry["increased"] = None
        entry["decreased"] = None
        entry["delta_distribution"] = {}
        if entry["changed_rows"] and max_transitions:
            # NULL_LABEL, not NaN: `value_counts` drops NaN, and for a
            # categorical column "became null" is the single most interesting
            # transition there is — dropping it renders the detail blank on
            # exactly the rows worth looking at.
            pairs = pd.DataFrame(
                {
                    "from": _stringify(b_series[changed]),
                    "to": _stringify(a_series[changed]),
                }
            )
            counts = pairs.value_counts(dropna=False).head(max_transitions)
            entry["top_transitions"] = [
                {"from": str(idx[0]), "to": str(idx[1]), "rows": int(n)}
                for idx, n in counts.items()
            ]

    entry["changed_fraction"] = (entry["changed_rows"] / total) if total else 0.0
    return entry


def diff_cells(
    aligned: _Aligned | None,
    epsilon: float = CELL_EPSILON,
    max_transitions: int = CELL_TRANSITIONS,
) -> dict | None:
    """Per-cell equality across every column shared by both sides.

    This is the check that ``coverage`` looks like but is not. Only columns
    that actually moved are reported; the shared-column count is carried so
    "0 of 87 columns moved" is a positive statement rather than an absence.
    """
    if aligned is None:
        return None
    shared_columns = [
        str(c)
        for c in aligned.before.columns
        if c in set(aligned.after.columns) and str(c) not in set(aligned.key)
    ]
    changed_columns = []
    for column in shared_columns:
        b_series, a_series = aligned.column_pair(column)
        entry = _compare_cells(b_series, a_series, epsilon, max_transitions)
        if entry["changed_rows"]:
            changed_columns.append(entry)
    changed_columns.sort(key=lambda e: (-e["changed_rows"], e["column"]))
    return {
        "shared_rows": int(len(aligned.shared)),
        "columns_compared": len(shared_columns),
        "columns_changed": len(changed_columns),
        "epsilon": epsilon,
        "changed": changed_columns,
    }


def _as_bool_int(series: pd.Series) -> pd.Series:
    """Coerce a possibly-object/bool/float label column to nullable Int8.

    NaN stays NaN so a null-vs-False change is not silently read as a flip.
    """
    if series.dtype == object:
        series = series.map(
            lambda v: v if v is None or (isinstance(v, float) and math.isnan(v)) else v
        )
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.round().astype("Int8")


# --------------------------------------------------------------------------
# per-file analysis
# --------------------------------------------------------------------------


def diff_schema(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    before_cols = [str(c) for c in before.columns]
    after_cols = [str(c) for c in after.columns]
    before_set, after_set = set(before_cols), set(after_cols)
    dtype_changes = {}
    for col in sorted(before_set & after_set):
        b, a = str(before[col].dtype), str(after[col].dtype)
        if b != a:
            dtype_changes[col] = {"before": b, "after": a}
    return {
        "columns_added": [c for c in after_cols if c not in before_set],
        "columns_removed": [c for c in before_cols if c not in after_set],
        "dtype_changed": dtype_changes,
        "columns_before": len(before_cols),
        "columns_after": len(after_cols),
    }


def diff_coverage(
    before: pd.DataFrame, after: pd.DataFrame, epsilon: float = COVERAGE_EPSILON
) -> list[dict]:
    """notna fraction per column, before vs after, largest move first.

    Deleting rows shifts every column's fraction by a hair, so a move smaller
    than ``epsilon`` is dropped — otherwise a 50-row deletion reports all 83
    columns as "changed" at ±0.00% and buries the one that really moved.
    Absolute notna counts are always carried in the JSON report, so a
    below-threshold move is inspectable rather than lost.
    """
    cov_b, cov_a = _coverage(before), _coverage(after)
    rows = []
    for col in sorted(set(cov_b) | set(cov_a)):
        b = cov_b.get(col)
        a = cov_a.get(col)
        if b is None or a is None:
            delta = None
        else:
            delta = a[0] - b[0]
            if abs(delta) < epsilon:
                continue
        rows.append(
            {
                "column": col,
                "before": None if b is None else b[0],
                "after": None if a is None else a[0],
                "delta": delta,
                "notna_before": None if b is None else b[1],
                "notna_after": None if a is None else a[1],
            }
        )
    rows.sort(key=lambda r: (r["delta"] is None, -abs(r["delta"] or 0.0)))
    return rows


def diff_keys(before: pd.DataFrame, after: pd.DataFrame, key: tuple[str, ...]) -> dict | None:
    missing = [c for c in key if c not in before.columns or c not in after.columns]
    if missing:
        return {"error": f"key column(s) absent on one side: {missing}"}
    b_keys = set(_key_series(before, key))
    a_keys = set(_key_series(after, key))
    only_before = b_keys - a_keys
    only_after = a_keys - b_keys
    return {
        "key": list(key),
        "keys_before": len(b_keys),
        "keys_after": len(a_keys),
        "only_in_before": len(only_before),
        "only_in_after": len(only_after),
        "shared": len(b_keys & a_keys),
        "sample_only_in_before": sorted(only_before)[:5],
        "sample_only_in_after": sorted(only_after)[:5],
    }


def diff_labels(aligned: _Aligned | None) -> dict | None:
    if aligned is None:
        return None
    b_idx, a_idx = aligned.before, aligned.after
    if LABEL_COLUMN not in b_idx.columns or LABEL_COLUMN not in a_idx.columns:
        return None
    shared = aligned.shared

    b_raw, a_raw = aligned.column_pair(LABEL_COLUMN)
    b_lab = _as_bool_int(b_raw)
    a_lab = _as_bool_int(a_raw)
    changed = (b_lab != a_lab) & ~(b_lab.isna() & a_lab.isna())

    result: dict = {
        "shared_rows": int(len(shared)),
        "duplicate_keys_before": aligned.dupes_before,
        "duplicate_keys_after": aligned.dupes_after,
        "flips_total": int(changed.sum()),
        "flip_0_to_1": int(((b_lab == 0) & (a_lab == 1)).sum()),
        "flip_1_to_0": int(((b_lab == 1) & (a_lab == 0)).sum()),
        "flip_to_null": int((b_lab.notna() & a_lab.isna()).sum()),
        "flip_from_null": int((b_lab.isna() & a_lab.notna()).sum()),
        "base_rate_before": (float(b_lab.mean()) if len(b_lab) else None),
        "base_rate_after": (float(a_lab.mean()) if len(a_lab) else None),
        "breakdowns": {},
    }

    if result["flips_total"] == 0:
        return result

    flipped_keys = shared[changed.to_numpy()]
    direction = pd.Series("other", index=flipped_keys, dtype=object)
    direction[(b_lab == 0) & (a_lab == 1)] = "0_to_1"
    direction[(b_lab == 1) & (a_lab == 0)] = "1_to_0"
    direction[b_lab.notna() & a_lab.isna()] = "to_null"
    direction[b_lab.isna() & a_lab.notna()] = "from_null"
    direction = direction.loc[flipped_keys]

    for dim in FLIP_BREAKDOWNS:
        # Prefer the "after" value for the breakdown dimension; fall back to
        # "before" so a dimension only present on one side still reports.
        source = a_idx if dim in a_idx.columns else (b_idx if dim in b_idx.columns else None)
        if source is None:
            continue
        labels = source.loc[flipped_keys, dim].astype(str)
        table = pd.crosstab(labels, direction)
        # Sort by total flips descending, then group name — deterministic
        # regardless of which direction happens to appear first in the data.
        table = table.loc[table.sum(axis=1).sort_values(ascending=False, kind="stable").index]
        result["breakdowns"][dim] = {
            str(idx): {str(c): int(v) for c, v in row.items()} for idx, row in table.iterrows()
        }
    return result


def diff_values(aligned: _Aligned | None) -> dict | None:
    if aligned is None:
        return None
    if VALUE_COLUMN not in aligned.before.columns or VALUE_COLUMN not in aligned.after.columns:
        return None
    shared = aligned.shared

    b_raw, a_raw = aligned.column_pair(VALUE_COLUMN)
    b_val = pd.to_numeric(b_raw, errors="coerce")
    a_val = pd.to_numeric(a_raw, errors="coerce")
    both = b_val.notna() & a_val.notna()
    delta = (a_val - b_val).where(both)
    moved = both & (delta.abs() > VALUE_EPSILON)

    return {
        "column": VALUE_COLUMN,
        "shared_rows": int(len(shared)),
        "changed_rows": int(moved.sum()),
        "changed_fraction": (float(moved.mean()) if len(shared) else 0.0),
        "became_null": int((b_val.notna() & a_val.isna()).sum()),
        "became_present": int((b_val.isna() & a_val.notna()).sum()),
        "increased": int((delta > VALUE_EPSILON).sum()),
        "decreased": int((delta < -VALUE_EPSILON).sum()),
        "delta_distribution": _quantiles(delta[moved]),
        "abs_delta_distribution": _quantiles(delta[moved].abs()),
    }


def diff_file(
    before_path: Path,
    after_path: Path,
    key: tuple[str, ...],
    coverage_epsilon: float = COVERAGE_EPSILON,
    cell_epsilon: float = CELL_EPSILON,
    with_cells: bool = True,
) -> dict:
    before = _read(before_path)
    after = _read(after_path)
    if before is None and after is None:
        return {"status": "absent_both"}
    if before is None:
        return {
            "status": "added",
            "rows_after": int(len(after)),
            "columns_after": [str(c) for c in after.columns],
        }
    if after is None:
        return {
            "status": "removed",
            "rows_before": int(len(before)),
            "columns_before": [str(c) for c in before.columns],
        }

    report: dict = {
        "status": "present_both",
        "rows_before": int(len(before)),
        "rows_after": int(len(after)),
        "rows_delta": int(len(after) - len(before)),
        "schema": diff_schema(before, after),
        "coverage": diff_coverage(before, after, coverage_epsilon),
    }
    if key:
        report["keys"] = diff_keys(before, after, key)
        aligned = _align(before, after, key)
        labels = diff_labels(aligned)
        if labels is not None:
            report["labels"] = labels
        values = diff_values(aligned)
        if values is not None:
            report["values"] = values
        if with_cells:
            cells = diff_cells(aligned, cell_epsilon)
            if cells is not None:
                report["cells"] = cells
    return report


def diff_json_file(before_path: Path, after_path: Path) -> dict:
    b_exists, a_exists = before_path.exists(), after_path.exists()
    if not b_exists and not a_exists:
        return {"status": "absent_both"}
    if not b_exists:
        return {"status": "added"}
    if not a_exists:
        return {"status": "removed"}
    before_text = before_path.read_bytes()
    after_text = after_path.read_bytes()
    if before_text == after_text:
        return {"status": "identical", "bytes": len(after_text)}

    def _top_keys(raw: bytes) -> list[str]:
        try:
            parsed = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return []
        return sorted(parsed) if isinstance(parsed, dict) else []

    b_keys, a_keys = _top_keys(before_text), _top_keys(after_text)
    return {
        "status": "changed",
        "bytes_before": len(before_text),
        "bytes_after": len(after_text),
        "top_level_keys_added": [k for k in a_keys if k not in set(b_keys)],
        "top_level_keys_removed": [k for k in b_keys if k not in set(a_keys)],
    }


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------


def _fmt_pct(value: float | None) -> str:
    return "   n/a" if value is None else f"{value * 100:6.2f}%"


def render_text(
    report: dict, coverage_limit: int, cell_limit: int = 25, out=sys.stdout
) -> None:
    write = out.write
    write("=" * 78 + "\n")
    write("curated snapshot diff\n")
    write(f"  before : {report['before']}\n")
    write(f"  after  : {report['after']}\n")
    write("=" * 78 + "\n\n")

    for name, file_report in report["files"].items():
        status = file_report["status"]
        write(f"-- {name} " + "-" * max(0, 74 - len(name)) + "\n")
        if status != "present_both":
            write(f"   status: {status.upper()}\n\n")
            continue

        delta = file_report["rows_delta"]
        write(
            f"   rows: {file_report['rows_before']:,} -> "
            f"{file_report['rows_after']:,}  ({delta:+,})\n"
        )

        schema = file_report["schema"]
        added, removed, dtypes = (
            schema["columns_added"],
            schema["columns_removed"],
            schema["dtype_changed"],
        )
        if not (added or removed or dtypes):
            write(f"   schema: unchanged ({schema['columns_after']} columns)\n")
        else:
            write(f"   schema: {schema['columns_before']} -> {schema['columns_after']} columns\n")
            if added:
                write(f"     + added   ({len(added)}): {', '.join(added)}\n")
            if removed:
                write(f"     - removed ({len(removed)}): {', '.join(removed)}\n")
            for col, change in dtypes.items():
                write(f"     ~ dtype {col}: {change['before']} -> {change['after']}\n")

        keys = file_report.get("keys")
        if keys:
            if "error" in keys:
                write(f"   keys: {keys['error']}\n")
            elif keys["only_in_before"] == 0 and keys["only_in_after"] == 0:
                write(f"   keys: identical ({keys['shared']:,} on {'+'.join(keys['key'])})\n")
            else:
                write(
                    f"   keys ({'+'.join(keys['key'])}): "
                    f"{keys['only_in_before']:,} only-before, "
                    f"{keys['only_in_after']:,} only-after, "
                    f"{keys['shared']:,} shared\n"
                )
                for side in ("before", "after"):
                    sample = keys[f"sample_only_in_{side}"]
                    if sample:
                        shown = ", ".join(s.replace("\x1f", "|") for s in sample)
                        write(f"     e.g. only-in-{side}: {shown}\n")

        labels = file_report.get("labels")
        if labels:
            if labels["flips_total"] == 0:
                write(
                    f"   labels: no {LABEL_COLUMN} flips "
                    f"({labels['shared_rows']:,} shared rows, base rate "
                    f"{labels['base_rate_before']:.4f})\n"
                )
            else:
                write(
                    f"   labels: {labels['flips_total']:,} {LABEL_COLUMN} flips "
                    f"of {labels['shared_rows']:,} shared rows\n"
                )
                write(
                    f"     0->1 {labels['flip_0_to_1']:,}   "
                    f"1->0 {labels['flip_1_to_0']:,}   "
                    f"->null {labels['flip_to_null']:,}   "
                    f"null-> {labels['flip_from_null']:,}\n"
                )
                write(
                    f"     base rate {labels['base_rate_before']:.4f} -> "
                    f"{labels['base_rate_after']:.4f}\n"
                )
                for dim, table in labels["breakdowns"].items():
                    write(f"     by {dim}:\n")
                    for group, counts in list(table.items())[:20]:
                        parts = "  ".join(f"{k} {v:,}" for k, v in sorted(counts.items()))
                        write(f"       {group:<28} {parts}\n")
            if labels["duplicate_keys_before"] or labels["duplicate_keys_after"]:
                write(
                    f"     WARNING duplicate keys dropped: "
                    f"{labels['duplicate_keys_before']:,} before, "
                    f"{labels['duplicate_keys_after']:,} after\n"
                )

        values = file_report.get("values")
        if values:
            if (
                values["changed_rows"] == 0
                and not values["became_null"]
                and not values["became_present"]
            ):
                write(f"   values: {VALUE_COLUMN} unchanged\n")
            else:
                write(
                    f"   values: {VALUE_COLUMN} changed on {values['changed_rows']:,} "
                    f"rows ({values['changed_fraction'] * 100:.2f}% of shared)\n"
                )
                write(
                    f"     up {values['increased']:,}   down {values['decreased']:,}   "
                    f"->null {values['became_null']:,}   null-> {values['became_present']:,}\n"
                )
                dist = values["delta_distribution"]
                if dist:
                    write(
                        "     delta  min {min:.3g}  p05 {p05:.3g}  med {median:.3g}  "
                        "p95 {p95:.3g}  max {max:.3g}  mean {mean:.3g}\n".format(**dist)
                    )

        cells = file_report.get("cells")
        if cells:
            if cells["columns_changed"] == 0:
                write(
                    f"   cells: no value changes in any of {cells['columns_compared']} "
                    f"shared non-key columns ({cells['shared_rows']:,} shared rows)\n"
                )
            else:
                write(
                    f"   cells: {cells['columns_changed']} of {cells['columns_compared']} "
                    f"shared non-key columns moved "
                    f"(top {cell_limit}, {cells['shared_rows']:,} shared rows)\n"
                )
                write(f"     {'column':<34} {'rows':>9} {'pct':>7}  detail\n")
                for entry in cells["changed"][:cell_limit]:
                    detail = ""
                    if entry["kind"] == "numeric":
                        dist = entry["delta_distribution"]
                        detail = f"up {entry['increased']:,} down {entry['decreased']:,}"
                        if entry["became_null"] or entry["became_present"]:
                            detail += (
                                f" ->null {entry['became_null']:,}"
                                f" null-> {entry['became_present']:,}"
                            )
                        if dist:
                            detail += (
                                "  delta min {min:.3g} med {median:.3g} "
                                "max {max:.3g} mean {mean:.3g}".format(**dist)
                            )
                    else:
                        moves = entry.get("top_transitions", [])
                        detail = "; ".join(
                            f"{m['from']!r}->{m['to']!r} {m['rows']:,}" for m in moves
                        )
                    write(
                        f"     {entry['column']:<34} {entry['changed_rows']:>9,} "
                        f"{entry['changed_fraction'] * 100:>6.2f}%  {detail}\n"
                    )

        coverage = file_report["coverage"]
        if not coverage:
            write("   coverage: unchanged on every column\n")
        else:
            write(f"   coverage: {len(coverage)} column(s) moved (top {coverage_limit})\n")
            write(f"     {'column':<38} {'before':>8} {'after':>8} {'delta':>9}\n")
            for row in coverage[:coverage_limit]:
                d = row["delta"]
                d_str = "     n/a" if d is None else f"{d * 100:+8.2f}%"
                write(
                    f"     {row['column']:<38} {_fmt_pct(row['before']):>8} "
                    f"{_fmt_pct(row['after']):>8} {d_str:>9}\n"
                )
        write("\n")

    write("-- json artifacts " + "-" * 59 + "\n")
    for name, entry in report["json_files"].items():
        status = entry["status"]
        extra = ""
        if status == "changed":
            extra = f"  ({entry['bytes_before']:,} -> {entry['bytes_after']:,} bytes)"
            if entry["top_level_keys_added"]:
                extra += f"  +keys {entry['top_level_keys_added']}"
            if entry["top_level_keys_removed"]:
                extra += f"  -keys {entry['top_level_keys_removed']}"
        write(f"   {name:<32} {status}{extra}\n")
    write("\n")

    write("=" * 78 + "\n")
    if report["has_deltas"]:
        write("RESULT: DELTAS DETECTED\n")
        for line in report["delta_summary"]:
            write(f"  * {line}\n")
    else:
        write("RESULT: ZERO DELTAS across every category\n")
    write("=" * 78 + "\n")


def summarize(report: dict) -> tuple[bool, list[str]]:
    lines: list[str] = []
    for name, file_report in report["files"].items():
        status = file_report["status"]
        if status in {"added", "removed"}:
            lines.append(f"{name}: {status}")
            continue
        if status != "present_both":
            continue
        if file_report["rows_delta"]:
            lines.append(f"{name}: row count {file_report['rows_delta']:+,}")
        schema = file_report["schema"]
        if schema["columns_added"]:
            lines.append(
                f"{name}: {len(schema['columns_added'])} column(s) added "
                f"({', '.join(schema['columns_added'][:6])})"
            )
        if schema["columns_removed"]:
            lines.append(
                f"{name}: {len(schema['columns_removed'])} column(s) removed "
                f"({', '.join(schema['columns_removed'][:6])})"
            )
        if schema["dtype_changed"]:
            lines.append(f"{name}: {len(schema['dtype_changed'])} dtype change(s)")
        keys = file_report.get("keys") or {}
        if keys.get("only_in_before") or keys.get("only_in_after"):
            lines.append(
                f"{name}: key-set differs "
                f"({keys['only_in_before']:,} only-before / "
                f"{keys['only_in_after']:,} only-after)"
            )
        labels = file_report.get("labels")
        if labels and labels["flips_total"]:
            lines.append(
                f"{name}: {labels['flips_total']:,} label flips "
                f"({labels['flip_0_to_1']:,} 0->1, {labels['flip_1_to_0']:,} 1->0)"
            )
        values = file_report.get("values")
        if values and (values["changed_rows"] or values["became_null"] or values["became_present"]):
            lines.append(f"{name}: {VALUE_COLUMN} moved on {values['changed_rows']:,} rows")
        cells = file_report.get("cells")
        if cells and cells["columns_changed"]:
            top = cells["changed"][0]
            lines.append(
                f"{name}: cell values moved in {cells['columns_changed']} column(s), "
                f"largest {top['column']} on {top['changed_rows']:,} rows"
            )
        if file_report["coverage"]:
            top = file_report["coverage"][0]
            lines.append(
                f"{name}: coverage moved on {len(file_report['coverage'])} column(s), "
                f"largest {top['column']} {_fmt_pct(top['before']).strip()} -> "
                f"{_fmt_pct(top['after']).strip()}"
            )
    for name, entry in report["json_files"].items():
        if entry["status"] not in {"identical", "absent_both"}:
            lines.append(f"{name}: {entry['status']}")
    return bool(lines), lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True, help="baseline dir")
    parser.add_argument("--after", type=Path, required=True, help="comparison dir")
    parser.add_argument("--json", type=Path, default=None, help="write JSON report here")
    parser.add_argument(
        "--coverage-limit",
        type=int,
        default=25,
        help="max coverage rows printed per file (default 25)",
    )
    parser.add_argument(
        "--coverage-epsilon",
        type=float,
        default=COVERAGE_EPSILON,
        help=(
            "ignore notna-fraction moves smaller than this "
            f"(default {COVERAGE_EPSILON:g} = 0.01 percentage points)"
        ),
    )
    parser.add_argument(
        "--cell-limit",
        type=int,
        default=25,
        help="max changed columns printed in the per-cell section (default 25)",
    )
    parser.add_argument(
        "--cell-epsilon",
        type=float,
        default=CELL_EPSILON,
        help=(
            "numeric per-cell moves smaller than this are float round-trip, not "
            f"data (default {CELL_EPSILON:g})"
        ),
    )
    parser.add_argument(
        "--no-cells",
        action="store_true",
        help=(
            "skip the per-cell sweep over every shared column. It is the only "
            "part of the harness that can see a value-only change, so this is "
            "for interactive speed, never for certifying a step."
        ),
    )
    parser.add_argument(
        "--fail-on-delta",
        action="store_true",
        help="exit 1 when any delta is detected (default: always exit 0)",
    )
    args = parser.parse_args(argv)

    before_dir: Path = args.before.resolve()
    after_dir: Path = args.after.resolve()
    for path in (before_dir, after_dir):
        if not path.is_dir():
            parser.error(f"not a directory: {path}")

    report: dict = {
        "before": str(before_dir),
        "after": str(after_dir),
        "files": {},
        "json_files": {},
    }
    for name, key in FILE_KEYS.items():
        report["files"][name] = diff_file(
            before_dir / name,
            after_dir / name,
            key,
            args.coverage_epsilon,
            args.cell_epsilon,
            not args.no_cells,
        )
    for name in JSON_FILES:
        report["json_files"][name] = diff_json_file(before_dir / name, after_dir / name)

    has_deltas, delta_lines = summarize(report)
    report["has_deltas"] = has_deltas
    report["delta_summary"] = delta_lines

    render_text(report, args.coverage_limit, args.cell_limit)

    if args.json is not None:
        out_path: Path = args.json.resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"\nJSON report: {out_path}")

    if args.fail_on_delta and has_deltas:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
