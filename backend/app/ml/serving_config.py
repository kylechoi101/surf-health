"""Serving-configuration provenance: name the regime at serve time (end-state E5).

The problem this exists to fix, measured on the 120d serving-calibration fit
window (14,414 scored rows, 2026-08-07)::

    pre-router      (<= 07-21)     13,425   93.1%
    two-tier router (07-22..08-05)    989    6.9%
    current config  (post 08-06)        0    0.0%   <--
    8 distinct model_versions pooled inside that window

**The calibrator applied to today's probabilities is fitted 100% on superseded
configurations.** ``_drop_pin_era_rows`` patches exactly one of those
boundaries; the router switch and the winner churn are unpatched.

Nothing in ``forecast_history.parquet`` could say so. ``model_version`` records
the *registry winner*, which is not what computed ``p_exceed`` — the two-tier
router hands most beaches to the offset model while the registry still reads
``xgb-undersample-ensemble-curated-v0``. The three eras above had to be
reconstructed from **side effects**: ``served_offset_weight`` non-null, then
``persistence_floor_applied`` non-null.

And that reconstruction is not merely awkward — for one span it is *impossible*.
``served_offset_weight`` only entered ``_HISTORY_COLUMNS`` on **2026-07-29**
(commit ``2a4e6d1c4``), about seven days after the router went live ~07-22. So
**2026-07-22..07-28 was router-served but is logged as pre-router**, and no side
effect distinguishes it. It is reported as
:data:`ERA_ROUTER_LOGGING_GAP_UNKNOWABLE` rather than back-dated: a fabricated
retrospective label would be worse than an honest gap, and that gap is the whole
argument for recording a fingerprint *at serve time* instead of inferring one
later.

--------------------------------------------------------------------------------
What is IN the hash, and why
--------------------------------------------------------------------------------

The rule: **the hash covers what a human chose, not what the data produced.**
A configuration change must be unable to leave the fingerprint unchanged; a
daily refit of the same configuration must be unable to churn it.

``serving_path_version``
    Structural changes to the serve path that no constant captures — the
    override→floor swap, the router being added, the floor moving out of the
    ``serving_calibration is not None`` branch. Hand-maintained, and pinned by
    ``tests/test_serving_config.py`` so a bump is a deliberate, reviewed act.

``winner_branch``
    Which branch of ``_export_forecasts`` computed the probability. Winner churn
    (measured: 11 changes in 105 days) is a genuine serving-configuration change
    and *must* move the fingerprint — making that churn countable is precisely
    what Step 9 needs.

``probability_source``
    The estimator(s) that actually produced the number, plus the constants that
    decide which one a row gets: ``router`` name, ``models``,
    ``fresh_cutoff_days``, ``blend_end_days``. This is the 2026-07-22 boundary
    that had no marker at all. Note it records the models the serving path can
    draw from — **not** the per-row route; see below.

``floors`` / ``bands``
    ``_LOW_THRESHOLD`` (persistence floor + non-finite fallback),
    ``_HIGH_THRESHOLD`` (advisory floor), the four band cutpoints, and the
    recency bands the confidence cap fires on. Each of these writes directly
    into a served field (``p_exceed`` or ``risk_band``).

``serving_calibration`` *policy*
    Window length, minimum pairs/positives, top-step support floor, whether the
    pin-era exclusion is on, and whether a map was actually applied this run.

--------------------------------------------------------------------------------
What is deliberately OUT, and why
--------------------------------------------------------------------------------

**The fitted isotonic knots.** The serving calibrator is refit *every day* from
the log itself, so hashing its knots would make every run its own regime, the
composition report would read 0% live regime forever by construction, and the
fingerprint would answer no question. It is also unnecessary: the calibration
transform is already fully observable per row as the map
``p_exceed_precal -> p_exceed``. The fingerprint covers exactly the part that is
*not* recoverable from the row — which model produced ``p_exceed_precal``.

**Trained model weights, per-beach base margins, the training-data vintage.**
Same argument, and stronger: E1 asks for ≥60 days of history on *one serving
configuration*, and you cannot have 60 days without daily refits. Fitted
parameters drifting inside a fixed configuration is the stationary regime E1
wants, not a regime change.

**``served_offset_weight``.** A per-row function of data lag, not of
configuration — and it is already logged per row. Hashing it would split one
configuration into three fingerprints and make the fingerprint churn with
pipeline lag (measured in ``CLAUDE.md``: one day of lag moves ~144 beaches onto
a different model). Regime = which stack served; offset weight = where in that
stack the row went. Keeping them separate is the point.

**Beach identity, sample age, feature values.** Data, not configuration.

Known limitation, stated rather than hidden: ``serving_path_version`` is a human
promise. A serve-path edit that changes numbers without touching any constant
and without a bump would reuse a stale fingerprint. That is why the version is
asserted by test alongside the fingerprint it produces — the test fails on the
next edit and forces the decision to be made explicitly.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from app.ml import calibration

# Bump ONLY for a serve-path change that alters served numbers and is not
# already captured by a constant in the document below.
#
#   1  (<= 2026-07-21)  single-model serve path; positive persistence OVERRODE
#                       the model to 1.0, and p_exceed_precal was snapshotted
#                       AFTER that override.
#   2  (2026-07-22)     two-tier fresh/stale serve-time router added.
#   3  (2026-08-06)     persistence override -> post-calibration FLOOR; precal
#                       snapshotted before the floor; the non-finite fallback
#                       stopped returning 1.0 on persistence-positive rows; the
#                       floor moved out of the `serving_calibration is not None`
#                       branch.
#
# Step 8 (provenance) adds logging only and changes no served number, so it
# deliberately does NOT bump this — that is the "no churn" property in action.
SERVING_PATH_VERSION = 4

# 16 hex chars = 64 bits. Collision-free for any plausible number of distinct
# serving configurations, short enough to read in a parquet column or a report.
FINGERPRINT_LENGTH = 16

ROUTER_TWO_TIER = "two_tier_fresh_stale"

# --- Reconstructed eras for rows written before the fingerprint existed -------
# These are ONLY ever applied to rows with a null fingerprint. They are honest
# best-effort labels for history, not a substitute for the recorded value.
ERA_PRE_ROUTER = "pre_router"
ERA_ROUTER_LOGGING_GAP_UNKNOWABLE = "router_logging_gap_unknowable"
ERA_ROUTER_LOGGED = "router_pre_persistence_floor"
ERA_PERSISTENCE_FLOOR_PRE_FINGERPRINT = "persistence_floor_pre_fingerprint"

# The two-tier router merged in 00612cae and began serving ~2026-07-22 ...
ROUTER_LIVE_DATE = pd.Timestamp("2026-07-22")
# ... but served_offset_weight only entered _HISTORY_COLUMNS on 2026-07-29
# (commit 2a4e6d1c4). Rows between these two dates are router-served and
# indistinguishable from pre-router rows in the log. Do not back-date them.
OFFSET_WEIGHT_LOGGED_DATE = pd.Timestamp("2026-07-29")

LEGACY_PREFIX = "legacy:"


def _stable(value: Any) -> Any:
    """JSON-canonicalise numpy scalars and sets so the digest is reproducible."""
    if isinstance(value, Mapping):
        return {str(k): _stable(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted(str(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_stable(v) for v in value]
    item = getattr(value, "item", None)
    if callable(item) and not isinstance(value, (str, bytes)):
        try:
            value = item()
        except (TypeError, ValueError):  # pragma: no cover - defensive
            pass
    if isinstance(value, float):
        # Round to 9 dp so a float-repr wobble cannot masquerade as a config
        # change. Every constant in the document is a human-typed decimal.
        return round(value, 9)
    return value


def build_serving_config(
    *,
    winner: str,
    probability_source: Mapping[str, Any],
    calibration_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """The serving-configuration document the fingerprint is taken over.

    ``probability_source`` is assembled by the serve path *as it runs*, so it
    records the decisions actually taken. That is why a constant belonging to a
    branch this run did not enter (e.g. the persistence-guard blend alpha) is
    absent rather than hashed: changing it could not have moved this run's
    numbers, so it must not move this run's fingerprint.

    The band/floor constants are read off :mod:`app.ml.calibration` at call time
    (module attribute, not an import-time copy) so a change to one of them is
    observable — including by the test that proves it.
    """
    return {
        "serving_path_version": SERVING_PATH_VERSION,
        "winner_branch": str(winner),
        "probability_source": dict(probability_source),
        "floors": {
            "persistence_floor": float(calibration._LOW_THRESHOLD),
            "advisory_floor": float(calibration._HIGH_THRESHOLD),
            "nonfinite_fallback": float(calibration._LOW_THRESHOLD),
        },
        "bands": {
            "low": float(calibration._LOW_THRESHOLD),
            "high": float(calibration._HIGH_THRESHOLD),
            "very_high": float(calibration._VERY_HIGH_THRESHOLD),
            "confidence_cap_recency_bands": sorted(
                calibration._LOW_CONFIDENCE_RECENCY_BANDS
            ),
        },
        "serving_calibration": dict(calibration_policy),
    }


def config_fingerprint(document: Mapping[str, Any]) -> str:
    """Stable short digest of a serving-configuration document."""
    canonical = json.dumps(_stable(document), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


def _bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].notna()


def reconstruct_legacy_era(
    frame: pd.DataFrame, *, date_column: str = "date"
) -> pd.Series:
    """Best-effort era label for rows written before the fingerprint existed.

    Precedence is most-recent-marker-first, because the markers accumulate: a
    post-2026-08-06 row carries BOTH ``persistence_floor_applied`` and
    ``served_offset_weight``.

    The ``router_logging_gap_unknowable`` bucket is the honest one. Those rows
    were router-served and are logged exactly like pre-router rows; they are
    labelled as unknowable instead of being assigned to either era.
    """
    if date_column in frame.columns:
        dates = pd.to_datetime(frame[date_column], errors="coerce")
    else:
        dates = pd.to_datetime(frame.get("forecast_date"), errors="coerce")
    dates = pd.Series(dates, index=frame.index)

    has_floor = _bool_series(frame, "persistence_floor_applied").to_numpy()
    has_offset = _bool_series(frame, "served_offset_weight").to_numpy()
    in_gap = (
        (dates >= ROUTER_LIVE_DATE) & (dates < OFFSET_WEIGHT_LOGGED_DATE)
    ).fillna(False).to_numpy()

    era = np.where(
        has_floor,
        ERA_PERSISTENCE_FLOOR_PRE_FINGERPRINT,
        np.where(
            has_offset,
            ERA_ROUTER_LOGGED,
            np.where(in_gap, ERA_ROUTER_LOGGING_GAP_UNKNOWABLE, ERA_PRE_ROUTER),
        ),
    )
    return pd.Series(era, index=frame.index, dtype="object")


def regime_labels(frame: pd.DataFrame, *, date_column: str = "date") -> pd.Series:
    """Per-row regime key: the recorded fingerprint, else ``legacy:<era>``.

    Prefixing reconstructed labels makes the two kinds impossible to confuse in
    a report — a bare 16-hex key was recorded at serve time and is exact; a
    ``legacy:`` key was inferred after the fact and carries the caveats above.
    """
    if "serving_config_fingerprint" in frame.columns:
        # Built element-wise: `Series.where(..., other=None)` silently means
        # "use the default", i.e. NaN, which would then stringify to "nan" and
        # become a phantom regime key.
        recorded = [
            None if pd.isna(value) else (str(value).strip() or None)
            for value in frame["serving_config_fingerprint"]
        ]
    else:
        recorded = [None] * len(frame)
    legacy = reconstruct_legacy_era(frame, date_column=date_column)
    return pd.Series(
        [
            fingerprint if fingerprint else f"{LEGACY_PREFIX}{era}"
            for fingerprint, era in zip(recorded, legacy, strict=False)
        ],
        index=frame.index,
        dtype="object",
    )


def is_legacy_regime(key: str) -> bool:
    return str(key).startswith(LEGACY_PREFIX)


REGISTRY_FILE = "serving_config_registry.json"


def record_serving_config(
    curated_dir, fingerprint: str, document: Mapping[str, Any], *, seen_at: str
) -> dict:
    """Append-only fingerprint -> document registry.

    A bare hash in a parquet column is not provenance unless something can say
    what it *means*. This keeps the decode table next to the data, so the
    composition report is self-describing without git archaeology over committed
    ``system_health.json`` snapshots.
    """
    from pathlib import Path

    from app.core.json_safe import write_json

    path = Path(curated_dir) / REGISTRY_FILE
    registry: dict[str, Any] = {"fingerprints": {}}
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict) and isinstance(loaded.get("fingerprints"), dict):
                registry = loaded
        except (OSError, ValueError):  # pragma: no cover - a corrupt file must not kill a run
            registry = {"fingerprints": {}}
    entry = registry["fingerprints"].get(fingerprint) or {
        "first_seen": seen_at,
        "n_runs": 0,
    }
    entry["last_seen"] = seen_at
    entry["n_runs"] = int(entry.get("n_runs", 0)) + 1
    # Rewritten every run on purpose: if a document ever changed without the
    # fingerprint changing, the hash would be broken and the newest document is
    # the one that describes what actually served.
    entry["document"] = _stable(document)
    registry["fingerprints"][fingerprint] = entry
    registry["updated_at"] = seen_at
    write_json(path, registry)
    return registry
