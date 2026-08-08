"""Assay-regime stratification for every published metric (end-state E3).

``exceeds_stv`` is not one label. Culture rows (Enterolert / EPA 1600 / MF, MPN
or CFU per 100 mL) are judged against the 104 marine STV; San Diego ddPCR rows
(copies per 100 mL) against the CDPH-developed, EPA Region 9 approved 1413-copies
BAV. Both action values are correct — the problem is not the thresholds, it is
that a metric averaged over both is a metric of *no* population:

    1095d window, measured 2026-08-07
      ddPCR         15.4% of rows   51.8% of all positive labels   base rate 0.592
      culture       84.6% of rows   48.2% of positives             base rate 0.100

A pooled AUCPR over that mixture is dominated by a model's ability to separate
the two *assays* — which is free, since ddPCR is one county — and says almost
nothing about either regime. Worse, AUCPR is base-rate dependent, so the pooled
number moves whenever the assay MIX moves, with no change in skill.

So every metric this package publishes carries its stratified pair. The rule the
rest of the codebase follows:

    **No pooled figure is published without ``by_assay`` beside it.**

Nothing here re-derives the assay. ``is_pcr`` is decided once per sample by
:func:`app.data.pipeline.exceedance.is_pcr_measurement` — the same predicate that
picked the threshold — and carried through the beach_day day-collapse.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from app.ml.evaluation import classification_metrics

# Stratum keys. Deliberately not "san_diego"/"rest": the cut is the ASSAY, and
# conflating it with the county is the exact error this module exists to stop
# (San Diego's culture-only base rate is 0.0974, *below* the 0.1007 rest-of-CA
# figure -- it is not a dirtier coastline, it is a differently-labelled one).
CULTURE_KEY = "culture"
PCR_KEY = "pcr"
ASSAY_KEYS = (CULTURE_KEY, PCR_KEY)

# A stratum below this many rows, or with no positive/negative contrast, yields
# composition only. Reporting an AUCPR off 6 rows is worse than reporting none.
MIN_STRATUM_ROWS = 30


def as_pcr_mask(is_pcr: Sequence[Any] | np.ndarray | None, n_rows: int) -> np.ndarray | None:
    """Coerce a per-row assay indicator to a bool mask, or ``None`` if unusable.

    Accepts bool, 0/1 float (how it travels through the numeric feature matrix),
    or object/NA. A null is treated as culture: every non-PCR source in the
    pipeline leaves it unset, and PCR is the narrow, explicitly-flagged case.
    Length mismatch returns ``None`` rather than truncating -- a silently
    misaligned mask would attribute rows to the wrong regime, which is worse than
    publishing no stratification at all.
    """
    if is_pcr is None:
        return None
    array = np.asarray(is_pcr)
    if array.ndim != 1 or array.shape[0] != n_rows:
        return None
    if array.dtype == object:
        return np.array(
            [bool(v) if v is not None and v == v else False for v in array],  # noqa: PLR0124
            dtype=bool,
        )
    if array.dtype.kind == "f":
        return np.nan_to_num(array, nan=0.0) > 0.5
    return array.astype(bool)


def assay_composition(mask: np.ndarray, labels: np.ndarray) -> dict[str, float]:
    """How the pooled population is split — the context a pooled number needs.

    Published alongside every stratified block because the pooled figure moves
    with these fractions even when neither stratum's skill changes at all.
    """
    labels = np.asarray(labels)
    total = float(len(labels))
    positives = float(labels.sum()) if total else 0.0
    pcr_positives = float(labels[mask].sum()) if mask.any() else 0.0
    return {
        "n_rows": total,
        "pcr_row_fraction": float(mask.mean()) if total else float("nan"),
        "pcr_positive_fraction": (pcr_positives / positives) if positives else float("nan"),
        "culture_base_rate": (
            float(labels[~mask].mean()) if (~mask).any() else float("nan")
        ),
        "pcr_base_rate": float(labels[mask].mean()) if mask.any() else float("nan"),
    }


def stratified_metrics(
    labels: np.ndarray,
    probabilities: np.ndarray,
    is_pcr: Sequence[Any] | np.ndarray | None,
    *,
    metric_fn: Callable[[np.ndarray, np.ndarray], dict[str, float]] = classification_metrics,
) -> dict[str, Any] | None:
    """``{"culture": {...}, "pcr": {...}, "composition": {...}}`` or ``None``.

    ``None`` means the cut could not be made honestly (no assay indicator, or a
    misaligned one) — callers must then publish the pooled figure with an
    explicit note, never silently as if it were stratified.
    """
    labels = np.asarray(labels)
    probabilities = np.asarray(probabilities, dtype=float)
    if labels.size == 0 or labels.shape != probabilities.shape:
        return None
    mask = as_pcr_mask(is_pcr, labels.shape[0])
    if mask is None:
        return None

    out: dict[str, Any] = {"composition": assay_composition(mask, labels)}
    for key, selector in ((CULTURE_KEY, ~mask), (PCR_KEY, mask)):
        n_rows = int(selector.sum())
        block: dict[str, Any] = {
            "n_rows": float(n_rows),
            "n_positive": float(labels[selector].sum()) if n_rows else 0.0,
            "base_rate": float(labels[selector].mean()) if n_rows else float("nan"),
        }
        # Both classes must be present: average_precision_score / brier over a
        # single-class slice is either undefined or trivially perfect.
        if n_rows >= MIN_STRATUM_ROWS and len(np.unique(labels[selector])) > 1:
            try:
                block.update(metric_fn(labels[selector], probabilities[selector]))
            except Exception:  # pragma: no cover - a metric must never fail a run
                block["error"] = "metric_computation_failed"
        else:
            block["insufficient_support"] = True
        out[key] = block
    return out


def attach_stratified_metrics(
    metrics: dict[str, Any],
    labels: np.ndarray,
    probabilities: np.ndarray,
    is_pcr: Sequence[Any] | np.ndarray | None,
    *,
    metric_fn: Callable[[np.ndarray, np.ndarray], dict[str, float]] = classification_metrics,
    key: str = "by_assay",
) -> dict[str, Any]:
    """Add ``by_assay`` to an existing pooled metrics block, in place.

    When the cut cannot be made, writes ``{"unavailable": ...}`` rather than
    leaving the key absent — an absent key reads as "not stratified yet", an
    explicit marker reads as "stratification was attempted and why it failed",
    and only the second survives a consumer that greps for E3 compliance.
    """
    strata = stratified_metrics(labels, probabilities, is_pcr, metric_fn=metric_fn)
    metrics[key] = strata if strata is not None else {"unavailable": "no_assay_indicator"}
    return metrics


def stratified_scalar(
    labels: np.ndarray,
    values_fn: Callable[[np.ndarray, np.ndarray], Any],
    probabilities: np.ndarray,
    is_pcr: Sequence[Any] | np.ndarray | None,
    extra: dict[str, np.ndarray] | None = None,
) -> dict[str, Any] | None:
    """Stratify an arbitrary (labels, probabilities, **extra) -> value function.

    Used for the metrics that are not ``classification_metrics``-shaped — chiefly
    ``two_tier.within_beach_auroc``, which also needs the per-row beach ids, and
    which is the HEADLINE metric (E4): a global AUCPR can look strong while the
    within-beach number sits at 0.50, i.e. the model is a per-beach lookup table.
    """
    labels = np.asarray(labels)
    mask = as_pcr_mask(is_pcr, labels.shape[0])
    if mask is None or labels.size == 0:
        return None
    extra = extra or {}
    out: dict[str, Any] = {}
    for key, selector in ((CULTURE_KEY, ~mask), (PCR_KEY, mask)):
        if int(selector.sum()) < MIN_STRATUM_ROWS:
            out[key] = {"n_rows": float(selector.sum()), "insufficient_support": True}
            continue
        try:
            out[key] = values_fn(
                labels[selector],
                np.asarray(probabilities, dtype=float)[selector],
                **{name: np.asarray(arr)[selector] for name, arr in extra.items()},
            )
        except Exception:  # pragma: no cover
            out[key] = {"error": "metric_computation_failed"}
    out["composition"] = assay_composition(mask, labels)
    return out
