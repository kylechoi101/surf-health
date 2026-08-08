"""Accountability loop for the *served* forecast (model_truth.md audit, 2026-07-23).

The shipped backtests score sample-days — rows where a lab sample was taken that
morning, so the lagged risk-history features are fresh. The product serves every
beach every day, where the last sample is a median ~9 days old. Scored against
what actually followed, the served regime ran AUCPR ~0.24 (vs 0.63-0.70 claimed)
and the top of the probability scale was ~3x hot (served ~0.98 -> ~0.36
realized). This module closes that loop:

- ``append_forecast_history``: append-only log of what ``forecasts.parquet``
  actually served (post release-gate), keyed by beach/forecast-day/issue-time.
- ``served_performance``: score that log against the lab results that followed
  (same-day and strictly-forward D+1..D+3) -> ``system_health.json
  ["served_metrics"]`` — the deployment-regime truth, refreshed daily.
- ``fit_serving_calibration`` / ``apply_serving_calibration``: daily isotonic
  refit of served probability -> realized exceedance rate, applied at forecast
  export so the published ``p_exceed`` means what it says where it is served.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from app.core.json_safe import write_json
from app.data.pipeline.exceedance import is_pcr_measurement
from app.ml.assay_strata import CULTURE_KEY, MIN_STRATUM_ROWS, PCR_KEY
from app.ml.calibration import _VERY_HIGH_THRESHOLD
from app.ml.evaluation import sensitivity_at_specificity
from app.ml.serving_config import is_legacy_regime, regime_labels

HISTORY_FILE = "forecast_history.parquet"
CALIBRATION_FILE = "serving_calibration.json"

# Columns persisted per served forecast row. ``p_exceed`` is what the apps
# banded on (post every floor + serving calibration); ``p_exceed_precal`` is the
# pre-serving-calibration probability the daily isotonic refit trains on. For
# legacy rows (before the calibration layer existed) ``p_exceed_raw`` is that
# same quantity, so the fit falls back precal -> raw -> p_exceed.
_HISTORY_COLUMNS = [
    "beach_id",
    "forecast_date",
    "p_exceed",
    "p_exceed_raw",
    "p_exceed_precal",
    "risk_band",
    "sample_age_days",
    "model_version",
    # Did the positive-persistence floor bind on this row? Before 2026-08-06 the
    # serve path OVERRODE persistence positives to 1.0 rather than flooring them,
    # and captured p_exceed_precal after that override — so on exactly the rows
    # where the question mattered, the model's own probability was absent from
    # every artifact and the change could not be measured retrospectively. Null
    # on rows logged before this column existed.
    "persistence_floor_applied",
    # Two-tier provenance: 0 = ensemble served this row, 1 = offset model did,
    # in between = age-ramp blend; null when no router ran. model_version alone
    # cannot distinguish them — it records the registry winner (the ensemble)
    # even on rows the offset model produced.
    "served_offset_weight",
    # Which serving CONFIGURATION produced this row (E5) — see
    # app/ml/serving_config.py for exactly what the hash covers and what it
    # deliberately excludes. Null on every row logged before this column
    # existed, and that is correct: adding a column populates it going forward
    # only, which is how the 2026-07-22..07-28 router-logging hole was created
    # in the first place. Those rows get a `legacy:` era reconstructed from side
    # effects instead; a fabricated retrospective fingerprint would be worse
    # than an honest gap.
    "serving_config_fingerprint",
    "forecast_generated_at",
]
_PROBABILITY_COLUMNS = ("p_exceed", "p_exceed_raw", "p_exceed_precal")

# Lab results trail the forecast by days. A forecast row is matched to its
# same-day result when one exists, else the first result in D+1..D+3 — near
# enough for the daily risk statement, provably not visible to the forecast.
FORWARD_MATCH_DAYS = 3
# Trailing window for the isotonic refit: long enough for ~100+ positives at
# the ~6% served base rate, short enough to track model/regime drift.
_FIT_WINDOW_DAYS = 120
# Below these the fitted map is noise — serve the uncalibrated probability.
_MIN_FIT_PAIRS = 500
_MIN_FIT_POSITIVES = 25
# Minimum observations behind the isotonic's TOP step. PAVA will happily emit
# y=1.0 off a handful of rows, and this map publishes a public risk number: after
# the pin-era exclusion the top step was y=1.0 supported by exactly TWO rows —
# both Mission Bay stations on the same afternoon, i.e. one spatially-correlated
# event, not two observations. Any served probability above that x would have
# been published as a certainty on that basis. Trailing under-supported steps are
# collapsed into the highest adequately-supported level instead.
_MIN_TOP_STEP_SUPPORT = 10

# Fixed reliability-bin edges aligned with the public risk bands.
_BIN_EDGES = (0.0, 0.05, 0.10, 0.20, 0.30, 0.70, 1.0001)

# The live serving configuration should supply most of its own calibrator. Below
# EITHER bar the fit is reported as under-represented: `_MIN_FIT_PAIRS` is the
# same absolute bar the fit itself uses for "enough data to beat noise", and the
# fraction catches a window that is mostly some other configuration even when it
# is large. Measured 2026-08-07: the live regime supplied 0 of 14,414 pairs.
_MIN_LIVE_REGIME_FRACTION = 0.50

# Attached beside every AUCPR this module publishes (E4). Kept short on purpose
# — it repeats across every stratum, and the alternative (one caveat far away
# from the number) is exactly how the pooled figure got quoted for a year.
AUCPR_CAVEAT = (
    "AUCPR is base-rate dependent: it moves with the population mix at constant "
    "skill and is not comparable across strata or windows. Rank with AUROC; the "
    "headline daily-skill metric is two_tier.within_beach_auroc."
)

# Attached to every figure that still pools across serving configurations.
POOLED_REGIME_CAVEAT = (
    "Pooled across serving configurations (see by_regime). The window can "
    "straddle a router switch, a winner change, or the persistence "
    "override->floor change, so this number can average models that are not "
    "running."
)

HEADLINE_METRIC = "within_beach_auroc"


def serving_calibration_policy() -> dict:
    """The calibration constants that belong in the serving-config fingerprint.

    Exposed as a function rather than imported constants so ``serving_config``
    never has to import this module (which imports it) — and so the policy has
    exactly one definition.
    """
    return {
        "window_days": int(_FIT_WINDOW_DAYS),
        "min_pairs": int(_MIN_FIT_PAIRS),
        "min_positives": int(_MIN_FIT_POSITIVES),
        "min_top_step_support": int(_MIN_TOP_STEP_SUPPORT),
        "forward_match_days": int(FORWARD_MATCH_DAYS),
        "pin_era_exclusion": True,
    }


def daily_outcomes(observations: pd.DataFrame) -> pd.DataFrame:
    """Worst lab outcome per (beach_id, day): did ANY sample exceed the STV.

    Also carries ``outcome_is_pcr`` — whether that day held a molecular (ddPCR,
    copies/100 mL, 1413 BAV) result rather than a culture one (MPN/CFU, 104 STV).
    Every served metric is stratified on it (E3): a served probability scored
    against a ddPCR label is being asked a different question, at a ~6x different
    base rate, than the same probability scored against a culture label, and the
    pooled figure moves with the assay MIX at constant skill.

    ``method``/``units`` are optional so a caller holding a slimmer frame still
    gets outcomes, just unstratifiable ones.
    """
    frame = observations.loc[observations["exceeds_stv"].notna()].copy()
    frame["date"] = pd.to_datetime(frame["sample_date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["date"])
    if {"method", "units"}.issubset(frame.columns):
        # ANY molecular sample that day marks the day molecular. The alternative
        # (the assay of the worst sample) would flip regime whenever a culture
        # sample happened to be the worse one, making the strata non-stationary
        # for reasons that have nothing to do with the monitoring programme.
        frame["_is_pcr"] = is_pcr_measurement(frame["method"], frame["units"]).fillna(False)
    else:
        frame["_is_pcr"] = False
    grouped = frame.groupby(["beach_id", "date"], as_index=False).agg(
        exceeds_stv=("exceeds_stv", "max"), outcome_is_pcr=("_is_pcr", "max")
    )
    grouped["exceeded"] = grouped["exceeds_stv"].astype(bool).astype(int)
    grouped["outcome_is_pcr"] = grouped["outcome_is_pcr"].astype(bool)
    return grouped[["beach_id", "date", "exceeded", "outcome_is_pcr"]]


def append_forecast_history(curated_dir: Path) -> int:
    """Append the on-disk forecasts.parquet to the served-forecast log.

    Reads the file AFTER the release-gate decision, so the log records what is
    actually serving — the fresh forecast, or the gate-frozen previous one
    (whose rows are already logged, making the append a no-op). Idempotent:
    rows are keyed by (beach_id, forecast_date, forecast_generated_at).
    Returns the number of rows added.
    """
    forecast_path = curated_dir / "forecasts.parquet"
    if not forecast_path.exists():
        return 0
    current = pd.read_parquet(forecast_path)
    if current.empty:
        return 0
    for column in _HISTORY_COLUMNS:
        if column not in current.columns:
            current[column] = None
    current = current[_HISTORY_COLUMNS].copy()
    for column in _PROBABILITY_COLUMNS:
        current[column] = pd.to_numeric(current[column], errors="coerce")
    current["sample_age_days"] = pd.to_numeric(current["sample_age_days"], errors="coerce")

    history_path = curated_dir / HISTORY_FILE
    prior_rows = 0
    if history_path.exists():
        history = pd.read_parquet(history_path)
        prior_rows = len(history)
        combined = pd.concat([history, current], ignore_index=True)
    else:
        combined = current
    combined = combined.drop_duplicates(
        subset=["beach_id", "forecast_date", "forecast_generated_at"], keep="last"
    )
    # Atomic write — a crash mid-write must not corrupt the accountability log.
    tmp_path = history_path.with_suffix(".parquet.tmp")
    combined.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, history_path)
    return len(combined) - prior_rows


def _final_per_beach_day(history: pd.DataFrame) -> pd.DataFrame:
    """The last-issued forecast per (beach_id, day) — what a user last saw."""
    frame = history.copy()
    frame["date"] = pd.to_datetime(frame["forecast_date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["date"])
    frame["_issued"] = frame["forecast_generated_at"].astype(str)
    frame = (
        frame.sort_values(["beach_id", "date", "_issued"])
        .drop_duplicates(subset=["beach_id", "date"], keep="last")
        .drop(columns="_issued")
    )
    fit_input = pd.to_numeric(frame.get("p_exceed_precal"), errors="coerce")
    for fallback in ("p_exceed_raw", "p_exceed"):
        fit_input = fit_input.fillna(pd.to_numeric(frame.get(fallback), errors="coerce"))
    frame["p_fit"] = fit_input
    return frame


def _with_outcomes(final: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """Join realized outcomes: same-day, first strictly-forward, and matched."""
    same_day = outcomes.rename(
        columns={"exceeded": "outcome_same_day", "outcome_is_pcr": "assay_same_day"}
    )
    merged = final.merge(same_day, on=["beach_id", "date"], how="left")
    merged["outcome_forward"] = np.nan
    # Assay of whichever outcome actually matched, so a forward-matched row is
    # stratified by the regime of the sample that scored it -- not by the regime
    # of a same-day sample that never happened. Object dtype, because the value
    # is a tri-state (culture / ddPCR / unknown) and an unknown must stay
    # distinguishable from culture; a float NaN column cannot hold a bool.
    merged["assay_forward"] = pd.Series(pd.NA, index=merged.index, dtype="object")
    for offset in range(1, FORWARD_MATCH_DAYS + 1):
        shifted = outcomes.copy()
        shifted["date"] = shifted["date"] - pd.Timedelta(days=offset)
        merged = merged.merge(
            shifted.rename(
                columns={"exceeded": f"_fwd_{offset}", "outcome_is_pcr": f"_fwda_{offset}"}
            ),
            on=["beach_id", "date"],
            how="left",
        )
        fresh = (merged["outcome_forward"].isna() & merged[f"_fwd_{offset}"].notna()).to_numpy()
        merged["assay_forward"] = np.where(
            fresh, merged[f"_fwda_{offset}"].to_numpy(dtype=object), merged["assay_forward"]
        )
        merged["outcome_forward"] = merged["outcome_forward"].fillna(merged[f"_fwd_{offset}"])
        merged = merged.drop(columns=[f"_fwd_{offset}", f"_fwda_{offset}"])
    merged["outcome_matched"] = merged["outcome_same_day"].fillna(merged["outcome_forward"])
    merged["assay_matched"] = (
        merged["assay_same_day"].astype(object).where(
            merged["assay_same_day"].notna(), merged["assay_forward"]
        )
    )
    return merged


def _matched_from_disk(
    curated_dir: Path,
) -> tuple[pd.DataFrame, int, pd.Timestamp] | None:
    """(final forecasts joined to outcomes, history rows, max outcome date)."""
    history_path = curated_dir / HISTORY_FILE
    observations_path = curated_dir / "observations.parquet"
    if not history_path.exists() or not observations_path.exists():
        return None
    history = pd.read_parquet(history_path)
    if history.empty:
        return None
    # method/units are what make the assay cut possible (E3). They were NOT in
    # this column list until 2026-08-08, so `daily_outcomes` took its
    # "unstratifiable" branch on every real run and reported the whole served
    # population as culture: the shipped 2026-08-07 payload reads
    # `pcr: {n_pairs: 0}` against 1,175 ddPCR observations in the same window.
    # A stratification that silently resolves to "all one stratum" is worse than
    # none — it looks like evidence that the mix is clean. Selected optionally so
    # a slim observations frame still yields (unstratified) outcomes.
    _wanted = ["beach_id", "sample_date", "exceeds_stv", "method", "units"]
    try:
        import pyarrow.parquet as _pq

        available = set(_pq.ParquetFile(observations_path).schema_arrow.names)
    except Exception:  # pragma: no cover - fall back to the guaranteed columns
        available = {"beach_id", "sample_date", "exceeds_stv"}
    observations = pd.read_parquet(
        observations_path, columns=[c for c in _wanted if c in available]
    )
    outcomes = daily_outcomes(observations)
    matched = _with_outcomes(_final_per_beach_day(history), outcomes)
    return matched, len(history), outcomes["date"].max() if len(outcomes) else pd.NaT


def _score(pairs: pd.DataFrame, outcome_column: str) -> dict | None:
    """Probability-quality metrics of served p_exceed against one outcome column."""
    subset = pairs.dropna(subset=["p_exceed", outcome_column])
    if subset.empty:
        return None
    labels = subset[outcome_column].astype(int).to_numpy()
    probabilities = subset["p_exceed"].astype(float).to_numpy()
    base_rate = float(labels.mean())
    record: dict[str, float | int] = {
        "n_pairs": int(len(subset)),
        "n_positive": int(labels.sum()),
        "base_rate": round(base_rate, 4),
        "brier": round(float(brier_score_loss(labels, probabilities)), 4),
        # The bar an uninformative flat constant sets — the audit found the
        # served probabilities losing to it, so it ships alongside every day.
        "brier_flat_base_rate": round(float(np.mean((base_rate - labels) ** 2)), 4),
    }
    if 0 < labels.sum() < len(labels):
        record["aucpr"] = round(float(average_precision_score(labels, probabilities)), 4)
        # E4: no AUCPR ships without it. The caveat travels WITH the number
        # rather than sitting in a header, because a consumer reads the number.
        record["aucpr_caveat"] = AUCPR_CAVEAT
        record["auroc"] = round(float(roc_auc_score(labels, probabilities)), 4)
        operating = sensitivity_at_specificity(labels, probabilities, 0.87)
        record["sensitivity_at_spec_0_87"] = round(float(operating["sensitivity"]), 4)
    return record


def _band_operating(pairs: pd.DataFrame) -> dict | None:
    """How the public Low-vs-warning banding performed against same-day truth."""
    subset = pairs.dropna(subset=["outcome_same_day"])
    subset = subset[subset["risk_band"].notna()]
    if subset.empty:
        return None
    labels = subset["outcome_same_day"].astype(int)
    warned = subset["risk_band"].astype(str) != "Low"
    positives = labels == 1
    negatives = labels == 0
    return {
        "n_pairs": int(len(subset)),
        "exceedances": int(positives.sum()),
        "sensitivity": (
            round(float((warned & positives).sum() / positives.sum()), 4)
            if positives.any()
            else None
        ),
        "specificity": (
            round(float((~warned & negatives).sum() / negatives.sum()), 4)
            if negatives.any()
            else None
        ),
        "exceedances_shown_low": int((~warned & positives).sum()),
        "false_alarms": int((warned & negatives).sum()),
    }


def _calibration_bins(pairs: pd.DataFrame) -> list[dict]:
    """Reliability table: served p_exceed vs realized rate, band-aligned bins."""
    subset = pairs.dropna(subset=["p_exceed", "outcome_matched"])
    probabilities = subset["p_exceed"].astype(float)
    labels = subset["outcome_matched"].astype(int)
    bins: list[dict] = []
    for low, high in zip(_BIN_EDGES[:-1], _BIN_EDGES[1:], strict=False):
        mask = (probabilities >= low) & (probabilities < high)
        if int(mask.sum()) == 0:
            continue
        bins.append(
            {
                "p_range": [low, min(high, 1.0)],
                "n": int(mask.sum()),
                "predicted_mean": round(float(probabilities[mask].mean()), 4),
                "actual_rate": round(float(labels[mask].mean()), 4),
            }
        )
    return bins


def _assay_subsets(pairs: pd.DataFrame, assay_column: str) -> dict[str, pd.DataFrame]:
    """Split served rows into culture / ddPCR by the assay that produced the LABEL.

    Rows whose assay is unknown (no matched outcome, or a history predating the
    method columns) are excluded from BOTH strata rather than defaulted into
    culture -- a default would quietly inflate whichever stratum absorbed them.
    """
    if assay_column not in pairs.columns:
        return {}
    assay = pairs[assay_column]
    known = assay.notna()
    flag = assay.fillna(False).astype(bool)
    return {
        CULTURE_KEY: pairs[known & ~flag],
        PCR_KEY: pairs[known & flag],
    }


def _score_by_assay(
    pairs: pd.DataFrame,
    outcome_column: str,
    assay_column: str,
    *,
    pooled_regimes: bool,
) -> dict:
    """``_score`` per assay regime, plus the composition the pooled figure hides.

    ``pooled_regimes`` says whether THIS call still spans several serving
    configurations. Splitting by assay does not un-pool the regimes, so a
    stratified block computed at the top level is still an average over
    models that may not be running, and has to say so — the two cuts are
    independent and a figure can be honest about one and wrong about the
    other.
    """
    subsets = _assay_subsets(pairs, assay_column)
    if not subsets:
        return {"unavailable": "no_assay_indicator"}
    out: dict[str, object] = {}
    for key, subset in subsets.items():
        scored = subset.dropna(subset=["p_exceed", outcome_column])
        if len(scored) < MIN_STRATUM_ROWS:
            out[key] = {"n_pairs": int(len(scored)), "insufficient_support": True}
            continue
        block = _score(subset, outcome_column) or {
            "n_pairs": int(len(scored)),
            "insufficient_support": True,
        }
        if pooled_regimes and "aucpr" in block:
            block["pooled_across_regimes"] = True
            block["pooled_caveat"] = POOLED_REGIME_CAVEAT
        out[key] = block
    scored_all = pairs.dropna(subset=["p_exceed", outcome_column])
    n_all = int(len(scored_all))
    n_pcr = int(
        len(subsets[PCR_KEY].dropna(subset=["p_exceed", outcome_column]))
    )
    out["composition"] = {
        "n_pairs": n_all,
        "pcr_pair_fraction": round(n_pcr / n_all, 4) if n_all else None,
    }
    return out


def _regime_subsets(pairs: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split served rows by the serving CONFIGURATION that produced them.

    Keyed on the recorded ``serving_config_fingerprint`` where present, else on
    a ``legacy:`` era reconstructed from side effects. Regimes are not merged
    when small — a thin regime is reported as thin, because "the current
    configuration has 40 rows" is the finding, not a rounding error.
    """
    if pairs.empty:
        return {}
    keys = regime_labels(pairs)
    return {str(key): pairs.loc[keys == key] for key in dict.fromkeys(keys)}


def _score_by_regime(pairs: pd.DataFrame) -> dict:
    """``_score`` per serving configuration, with the assay cut nested inside.

    The two stratifications compose rather than compete: regime is *which stack
    served the row*, assay is *which labelling universe scored it*. A pooled
    figure hides both, and they hide different things — pooling regimes averages
    models that are not running, pooling assays averages two action values at a
    ~6x base-rate difference.
    """
    out: dict[str, object] = {}
    for key, subset in _regime_subsets(pairs).items():
        scored_same = subset.dropna(subset=["p_exceed", "outcome_same_day"])
        block: dict[str, object] = {
            "n_rows": int(len(subset)),
            "n_scored_same_day": int(len(scored_same)),
            "is_reconstructed": key.startswith("legacy:"),
        }
        if len(scored_same) >= MIN_STRATUM_ROWS:
            same_day = _score(subset, "outcome_same_day")
            if same_day:
                same_day["by_assay"] = _score_by_assay(
                    subset, "outcome_same_day", "assay_same_day", pooled_regimes=False
                )
                block["same_day"] = same_day
        else:
            block["insufficient_support"] = True
        forward_scored = subset.dropna(subset=["p_exceed", "outcome_forward"])
        if len(forward_scored) >= MIN_STRATUM_ROWS:
            forward = _score(subset, "outcome_forward")
            if forward:
                forward["by_assay"] = _score_by_assay(
                    subset, "outcome_forward", "assay_forward", pooled_regimes=False
                )
                block[f"forward_1_{FORWARD_MATCH_DAYS}d"] = forward
        out[key] = block
    return out


def fit_window_composition(pairs: pd.DataFrame) -> dict:
    """What the serving calibrator is actually fitted on, by serving regime.

    Reported the way ``n_pin_era_excluded`` already is. The measured 2026-08-07
    breakdown of the 120d window — pre-router 93.1%, router 6.9%, current
    configuration 0.0%, eight ``model_version``s pooled — is the reason this
    exists: none of it was visible from the payload, and ``model_version`` could
    not have shown it (it records the registry winner, not the model that
    computed ``p_exceed``).
    """
    if pairs.empty:
        return {"n_pairs": 0, "by_regime": {}, "by_model_version": {}}
    keys = regime_labels(pairs)
    counts = keys.value_counts()
    by_regime = {str(k): int(v) for k, v in counts.items()}
    fingerprinted = sum(n for name, n in by_regime.items() if not is_legacy_regime(name))
    versions = (
        pairs["model_version"].astype(str).value_counts()
        if "model_version" in pairs.columns
        else pd.Series(dtype=int)
    )
    return {
        "n_pairs": int(len(pairs)),
        "by_regime": by_regime,
        "n_distinct_regimes": int(len(by_regime)),
        "fingerprinted_pairs": fingerprinted,
        "fingerprinted_fraction": round(fingerprinted / len(pairs), 4),
        "by_model_version": {str(k): int(v) for k, v in versions.items()},
        "n_distinct_model_versions": int(len(versions)),
        "note": (
            "Regimes are keyed on the recorded serving_config_fingerprint where "
            "present, else on a 'legacy:' era reconstructed from side effects. "
            "model_version is NOT a regime key — it records the registry winner, "
            "not the model that computed p_exceed. The 2026-07-22..07-28 span "
            "was router-served but is indistinguishable from pre-router in the "
            "log (served_offset_weight only started being written 2026-07-29), "
            "so it is reported as router_logging_gap_unknowable rather than "
            "back-dated."
        ),
    }


def annotate_live_regime(
    payload: dict,
    live_fingerprint: str | None,
    *,
    min_pairs: int = _MIN_FIT_PAIRS,
    min_fraction: float = _MIN_LIVE_REGIME_FRACTION,
) -> dict:
    """Add the live-regime share of the fit window, and warn when it is thin.

    Deliberately a warning and NOT a filter. Filtering the calibrator to the
    live regime on 2026-08-07 leaves **0 pairs**, ``fit_serving_calibration``
    returns None, and the product serves uncalibrated probabilities — which are
    known to run hot. The choice today is stale data vs *no* data and stale
    wins; filtering becomes affordable only once Step 9 makes a configuration
    outlive the ~7 days it takes to calibrate one.
    """
    composition = payload.get("fit_window_composition")
    if not isinstance(composition, dict):
        return payload
    total = int(composition.get("n_pairs") or 0)
    by_regime: dict = composition.get("by_regime") or {}
    live_pairs = int(by_regime.get(str(live_fingerprint), 0)) if live_fingerprint else 0
    fraction = round(live_pairs / total, 4) if total else None
    composition["live_fingerprint"] = live_fingerprint
    composition["live_fingerprint_pairs"] = live_pairs
    composition["live_fingerprint_fraction"] = fraction
    warning = None
    if live_fingerprint is None:
        warning = (
            "No serving-config fingerprint was supplied for this run, so the "
            "calibrator's fit window cannot be checked against the "
            "configuration it is being applied to."
        )
    elif live_pairs < min_pairs or (fraction is not None and fraction < min_fraction):
        top = sorted(by_regime.items(), key=lambda kv: -kv[1])[:3]
        top_text = ", ".join(f"{name} {count}" for name, count in top)
        warning = (
            f"serving-calibration fit window is {fraction:.1%} live regime "
            f"({live_pairs} of {total} pairs, fingerprint {live_fingerprint}); "
            f"the map applied to today's probabilities is fitted mostly on "
            f"SUPERSEDED serving configurations (largest: {top_text}). Serving "
            "it anyway is deliberate — filtering to the live regime would leave "
            "too few pairs to fit and the product would serve uncalibrated "
            "probabilities, which run hot. This resolves when a configuration "
            "outlives its calibration window (REBUILD_STEPS.md Step 9)."
        )
    composition["under_represented_warning"] = warning
    if warning:
        print(f"[serving calibration] WARNING: {warning}", file=sys.stderr, flush=True)
    return payload


def served_performance(
    curated_dir: Path, windows: tuple[int, ...] = (90, 30)
) -> dict | None:
    """Score every served forecast against the lab results that followed.

    This is the audit's Test 4 (real forecast vs ground truth) wired into the
    daily pipeline: the numbers describe the product as deployed — stale
    between-sample rows included — not the fresh-sample backtest regime.
    """
    loaded = _matched_from_disk(curated_dir)
    if loaded is None:
        return None
    matched, history_rows, max_outcome_date = loaded
    if matched.empty:
        return None
    latest = matched["date"].max()
    payload: dict[str, object] = {
        "definition": (
            "Served p_exceed from forecast_history.parquet (final issue per "
            "beach-day) scored against observations.parquet worst-sample-per-day; "
            "same_day = outcome on the forecast day, forward = first outcome in "
            f"D+1..D+{FORWARD_MATCH_DAYS} (provably unseen by the forecast)."
        ),
        "history_rows": int(history_rows),
        "final_forecast_rows": int(len(matched)),
        "history_span_days": int((latest - matched["date"].min()).days) + 1,
        # E4/E5. This is the "how good is the product" surface, so it says which
        # number is the headline and what the pooled ones are pooling over.
        "metric_guidance": {
            "headline_metric": HEADLINE_METRIC,
            "headline_location": (
                "model_registry.metrics.two_tier_diagnostics (and headline_metrics)"
            ),
            "headline_rationale": (
                "Global AUCPR/AUROC are dominated by BETWEEN-beach variance — a "
                "model scores well by knowing one beach is dirtier than another, "
                "with zero ability to tell Tuesday from Thursday at one beach. "
                "within_beach_auroc is the only published number that can see "
                "that failure."
            ),
            "aucpr_caveat": AUCPR_CAVEAT,
            "pooled_caveat": POOLED_REGIME_CAVEAT,
        },
    }
    # Falsifiability: of forecasts old enough that a result COULD have arrived
    # (the observation feed extends past their match window), how many ever got
    # one (audit measured ~10% — most published output is never checkable).
    checkable = matched[
        matched["date"] <= max_outcome_date - pd.Timedelta(days=FORWARD_MATCH_DAYS)
    ]
    if len(checkable):
        payload["verifiable_fraction"] = round(
            float(checkable["outcome_matched"].notna().mean()), 4
        )
    for window in windows:
        recent = matched[matched["date"] > latest - pd.Timedelta(days=window)]
        entry: dict[str, object] = {}
        same_day = _score(recent, "outcome_same_day")
        if same_day:
            band = _band_operating(recent)
            if band:
                same_day["band_operating"] = band
            # E3. These are the deployment-truth numbers -- the ones CLAUDE.md
            # says to cite for "how good is the product" -- so they are exactly
            # the figures that must not average two labelling universes.
            same_day["by_assay"] = _score_by_assay(
                recent, "outcome_same_day", "assay_same_day", pooled_regimes=True
            )
            # E5. And they must not average serving configurations either. The
            # pooled block is kept (consumers read it) but is now LABELLED as
            # pooled rather than presented as "the" number.
            same_day["pooled_across_regimes"] = True
            same_day["pooled_caveat"] = POOLED_REGIME_CAVEAT
            entry["same_day"] = same_day
        forward = _score(recent, "outcome_forward")
        if forward:
            forward["by_assay"] = _score_by_assay(
                recent, "outcome_forward", "assay_forward", pooled_regimes=True
            )
            forward["pooled_across_regimes"] = True
            forward["pooled_caveat"] = POOLED_REGIME_CAVEAT
            entry[f"forward_1_{FORWARD_MATCH_DAYS}d"] = forward
        reliability = _calibration_bins(recent)
        if reliability:
            entry["calibration_bins"] = reliability
            entry["calibration_bins_pooled_across_regimes"] = True
            entry["calibration_bins_by_assay"] = {
                key: _calibration_bins(subset)
                for key, subset in _assay_subsets(recent, "assay_matched").items()
            }
        regime_composition = {
            key: int(len(subset)) for key, subset in _regime_subsets(recent).items()
        }
        if regime_composition:
            entry["regime_composition"] = regime_composition
            entry["by_regime"] = _score_by_regime(recent)
        if entry:
            payload[f"window_{window}d"] = entry
    payload["generated_at"] = datetime.now(UTC).isoformat()
    return payload


def _drop_pin_era_rows(pairs: pd.DataFrame) -> pd.DataFrame:
    """Drop served rows whose ``p_fit`` is the old positive-persistence PIN, not a
    model output.

    Until 2026-08-06 the serve path did ``where(persistence >= 0.5, 1.0, p)``
    BEFORE snapshotting ``p_exceed_precal``, so on those rows the recorded
    "pre-calibration probability" is the constant 1.0. Measured on the 2026-08-05
    history: 482 of 13,813 rows in the 120d window, realizing 0.4149 — enough to
    pin the isotonic's top step at y=0.45 and cap EVERY served probability there,
    which made the Very High band unreachable and sent 47% of persistence-positive
    beaches to Moderate against a 0.632 realized rate.

    Identified as ``p_fit == 1.0`` AND no ``persistence_floor_applied`` value —
    that column only exists on rows written by the post-change code, so this is
    self-limiting: it excludes only legacy rows and stops firing entirely once the
    trailing window rolls past the change. A post-change row is never dropped,
    even if a model legitimately outputs 1.0.

    ⚠️ The self-limiting property has ONE exception. If
    ``hist_gbm_positive_persistence_guard`` ever won promotion it would serve
    precal 1.0 by definition (``training.py``, its own branch) *with* a non-null
    ``persistence_floor_applied``, so those rows would never be dropped and pin
    contamination would re-enter permanently. That is the same accepted
    consequence recorded on the guard function itself — but this is the module
    that claims the problem self-heals, so it has to carry the caveat too.

    ⚠️ Note what this exclusion does NOT do. Every pre-change persistence-positive
    row carried precal 1.0, so removing them leaves the legacy fit population
    entirely persistence-NEGATIVE, and the resulting map is then applied to a
    mixed one. Measured on the A/B holdout, it under-predicts the affected rows
    (mean 0.4444 against a 0.6324 realized rate) where a clean per-arm refit does
    not (0.6378). It cannot be fixed from history — the pin destroyed those
    x-values — and it decays only as the window rolls past the change.
    """
    if "persistence_floor_applied" not in pairs.columns:
        legacy = pd.Series(True, index=pairs.index)
    else:
        legacy = pairs["persistence_floor_applied"].isna()
    pinned = legacy & (pd.to_numeric(pairs["p_fit"], errors="coerce") >= 1.0)
    if not pinned.any():
        return pairs
    print(
        f"[serving calibration] excluded {int(pinned.sum())} pin-era rows "
        "(p_exceed_precal == 1.0 from the pre-2026-08-06 override).",
        file=sys.stderr, flush=True,
    )
    return pairs.loc[~pinned]


def _cap_undersupported_top_step(
    knots_x: np.ndarray,
    knots_y: np.ndarray,
    fit_probabilities: np.ndarray,
) -> tuple[np.ndarray, float, float | None]:
    """Collapse trailing isotonic steps that too few observations support.

    Returns ``(knots_y, y_cap, capped_from)`` — ``capped_from`` is the original
    ceiling when a cap was applied, else None. See ``_MIN_TOP_STEP_SUPPORT``.
    """
    if len(knots_x) < 2:
        return knots_y, float(knots_y.max(initial=0.0)), None
    predicted = np.interp(fit_probabilities, knots_x, knots_y)
    levels = np.unique(np.round(knots_y, 9))
    supported = [
        lvl for lvl in levels
        if int(np.isclose(predicted, lvl, atol=1e-9).sum()) >= _MIN_TOP_STEP_SUPPORT
    ]
    if not supported:
        return knots_y, float(knots_y.max()), None
    cap = float(max(supported))
    original = float(knots_y.max())
    if cap >= original:
        return knots_y, original, None
    print(
        f"[serving calibration] top step y={original:.4f} had "
        f"<{_MIN_TOP_STEP_SUPPORT} supporting rows; capped to y={cap:.4f}.",
        file=sys.stderr, flush=True,
    )
    return np.minimum(knots_y, cap), cap, original


def _warn_if_ceiling_suppresses_a_band(y_cap: float) -> str | None:
    """Warn when the map's ceiling has fallen below a published band cutpoint.

    The ceiling is whatever the top-supported step happens to be, and it moves as
    the trailing window rolls. Today it rests on ~19 rows from a two-week span in
    early May — when those age out, `y_max` drops to ~0.70 and then ~0.49, and at
    that point NO beach can be served Very High no matter what the model says.
    That is exactly the failure this whole change was about (a ceiling silently
    deciding a band is unreachable), and nothing else catches it: the anomaly
    gate's band check only fires when non-Low collapses to zero.
    """
    if y_cap >= _VERY_HIGH_THRESHOLD:
        return None
    message = (
        f"serving-calibration ceiling y_max={y_cap:.4f} is below the Very High "
        f"cutpoint ({_VERY_HIGH_THRESHOLD:.2f}) — that band is currently "
        "UNREACHABLE for every beach regardless of model output."
    )
    print(f"[serving calibration] WARNING: {message}", file=sys.stderr, flush=True)
    return message


def fit_serving_calibration(
    curated_dir: Path,
    *,
    window_days: int = _FIT_WINDOW_DAYS,
    min_pairs: int = _MIN_FIT_PAIRS,
    min_positives: int = _MIN_FIT_POSITIVES,
) -> dict | None:
    """Isotonic map: served (pre-calibration) probability -> realized rate.

    Fit on the trailing ``window_days`` of matched served-forecast/lab pairs.
    Returns None when history is too thin to beat noise — callers then serve
    the uncalibrated probability (exactly the pre-audit behavior).

    Pin-era rows are excluded (see ``_drop_pin_era_rows``): before 2026-08-06 the
    serve path OVERRODE persistence positives to 1.0 *before* ``p_exceed_precal``
    was captured, so their x-value is a constant, not a model output. Fitting on
    them caps this map's top step at the realized rate of that constant and
    mis-calibrates every post-change probability pushed through it.
    """
    loaded = _matched_from_disk(curated_dir)
    if loaded is None:
        return None
    matched = loaded[0]
    pairs = matched.dropna(subset=["p_fit", "outcome_matched"])
    if pairs.empty:
        return None
    latest = pairs["date"].max()
    pairs = pairs[pairs["date"] > latest - pd.Timedelta(days=window_days)]
    n_before_exclusion = len(pairs)
    pairs = _drop_pin_era_rows(pairs)
    n_pin_era_excluded = n_before_exclusion - len(pairs)
    if pairs.empty:
        return None
    labels = pairs["outcome_matched"].astype(int).to_numpy()
    probabilities = pairs["p_fit"].astype(float).to_numpy()
    n_positive = int(labels.sum())
    if len(pairs) < min_pairs or n_positive < min_positives or n_positive == len(pairs):
        return None
    model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    model.fit(probabilities, labels)
    knots_y, y_cap, capped_from = _cap_undersupported_top_step(
        np.asarray(model.X_thresholds_, dtype=float),
        np.asarray(model.y_thresholds_, dtype=float),
        probabilities,
    )
    calibrated = np.interp(probabilities, model.X_thresholds_, knots_y)
    base_rate = float(labels.mean())
    return {
        "x": [round(float(v), 6) for v in model.X_thresholds_],
        "y": [round(float(v), 6) for v in knots_y],
        "fitted_at": datetime.now(UTC).isoformat(),
        "window_days": int(window_days),
        "n_pairs": int(len(pairs)),
        "n_positive": n_positive,
        "n_pin_era_excluded": n_pin_era_excluded,
        # E5: what this map is actually fitted on. `n_pin_era_excluded` above
        # patches ONE configuration boundary (the persistence pin); this reports
        # every boundary in the window, including the ones nothing patches.
        # `annotate_live_regime` then adds the live-regime share and the warning.
        "fit_window_composition": fit_window_composition(pairs),
        # The map's ceiling and whether a thin top step was collapsed into it.
        # Without these the payload cannot distinguish "the model never scored
        # that high" from "the top of the scale was capped".
        "y_max": round(float(y_cap), 6),
        "top_step_capped_from": (
            None if capped_from is None else round(float(capped_from), 6)
        ),
        "min_top_step_support": int(_MIN_TOP_STEP_SUPPORT),
        # Non-null when the ceiling has fallen below a published band cutpoint,
        # i.e. that band is unreachable this run. Surfaces in system_health so the
        # condition is inspectable rather than only a stderr line in a CI log.
        "ceiling_warning": _warn_if_ceiling_suppresses_a_band(float(y_cap)),
        "brier_before": round(float(brier_score_loss(labels, probabilities)), 4),
        "brier_after": round(float(brier_score_loss(labels, calibrated)), 4),
        "brier_flat_base_rate": round(float(np.mean((base_rate - labels) ** 2)), 4),
    }


def apply_serving_calibration(probabilities: np.ndarray, mapping: dict) -> np.ndarray:
    """Piecewise-linear interpolation through the isotonic knots (monotone, so
    rank order — the part of the model that held up forward — is preserved).
    NaN passes through; a degenerate mapping is a no-op."""
    values = np.asarray(probabilities, dtype=float)
    knots_x = np.asarray(mapping.get("x", []), dtype=float)
    knots_y = np.asarray(mapping.get("y", []), dtype=float)
    if len(knots_x) < 2 or len(knots_x) != len(knots_y):
        return values
    return np.clip(np.interp(values, knots_x, knots_y), 0.0, 1.0)


def save_serving_calibration(curated_dir: Path, mapping: dict) -> None:
    write_json(curated_dir / CALIBRATION_FILE, mapping)
