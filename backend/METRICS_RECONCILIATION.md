# Metrics Reconciliation — spatial AUCPR gap (docs 0.590 vs disk 0.499)

**Author:** ML Evaluation & Honesty Engineer
**Date:** 2026-06-10
**Scope:** Why `data/curated/system_health.json` shows the deployed
`xgb_undersample_ensemble` at held-out **county AUCPR 0.4991 / beach AUCPR 0.8714**
while `CLAUDE.md` and commit `93923683d` cite **0.590 / 0.900**. What the honest
generalization number is. Status of the Searcy et al. 2018 benchmark.

---

## TL;DR

- The **0.499 county / 0.871 beach** numbers on disk are the **real, honest
  generalization metrics** — they are what the daily CI gate actually computes on
  leave-one-county-out / leave-one-beach-out holdouts, with production calibration.
- The **0.590 / 0.900** numbers cited in the docs come from commit `93923683d`'s
  message but were **never reproduced by the in-pipeline gate**. They are either an
  offline / `spatial_compare`-style number or a one-off that the committed CI path
  does not regenerate. Every system_health.json the gate has written since shows
  ~0.499.
- **Root cause is NOT the 6/15 shortlist trim** (commit `153f1368a`). That trim
  landed *after* the current system_health.json was written and has not yet run a
  daily refresh. The 0.499 was produced by the **full 12-county / 50-beach** sweep.
- The real cause of the offline-vs-gate gap is a **methodology difference between
  the offline `spatial_compare.py` and the in-gate `_spatial_holdout_fold_result`**:
  calibration, an inner train/valid split, and a different county-selection rule.
  Commit `93923683d`'s own message already conceded this ("the rest of the gap is
  the gate's calibration + inner-validation split") — it just didn't update the
  headline number to match.
- **0.499 county AUCPR over a 0.175 county pooled base rate, beating the 0.370
  persistence baseline, is the honest, modest lift.** The beach-level 0.871 (base
  rate 0.373, persistence 0.579) is much stronger because beaches retain memorable
  per-site base rates even when held out individually; the county number is the
  harder, more honest test of spatial generalization.
- **Searcy benchmark (sens 0.59 @ spec 0.87): NOT reproduced.** No per-row holdout
  prediction artifact (probabilities + labels) is persisted anywhere on disk, so it
  cannot be recomputed without a retrain. A reproducible
  `sensitivity_at_specificity()` helper has been added to `evaluation.py`; until a
  retrain pools and saves holdout predictions, the claim is flagged unverified.

---

## Evidence — the numbers on disk

`data/curated/system_health.json` (committed by `5d99a8587`, "daily forecast
refresh 2026-06-08", file mtime 2026-06-09):

| metric | county (folds=12) | beach (folds=50) |
|---|---|---|
| `spatial_*_xgb_undersample_ensemble` AUCPR | **0.4991** (L82) | **0.8714** (L70-71) |
| Brier | 0.1140 | 0.1130 |
| calibration_slope | **0.9873** (L85) | **0.8785** (L74) |
| precision@80recall | 0.4166 | 0.7641 |
| pooled positive_rate | **0.1750** | 0.3734 |
| persistence AUCPR (baseline) | **0.3700** (L60) | 0.5787 (L48) |

`spatial_backtest_strategy: "disabled"` (L25) and `promotion_policy.spatial_backtest_strategy: "shortlist"` (L196) — the
run that wrote this used **folds = 12 counties / 50 beaches**, i.e. the FULL
shortlist sweep, not 6/15.

## Evidence — the docs

`CLAUDE.md:150-153`:
> ensemble held-out **county AUCPR 0.507 → 0.590** (Brier 0.118 → 0.107),
> **beach 0.881 → 0.900** … Ensemble passes every gate (calib slopes county 1.26 /
> beach 1.16).

Commit `93923683d` ("feat(ml): train at 1095d window…", 2026-06-08 11:46 PDT)
message repeats the same 0.590 / 0.900 and slopes 1.26 / 1.16.

**The disk slopes are 0.987 / 0.879, not 1.26 / 1.16.** Slopes near 1.0 are *better*
calibrated than 1.26/1.16 (which over-disperse). So the docs are not only optimistic
on AUCPR, they cite the wrong (worse) calibration story too.

---

## Timeline (commit hashes + times)

1. **`93923683d`** 2026-06-08 11:46 PDT — flips CI training window 365 → 1095d.
   Workflow flags at this commit: `--spatial-county-limit 12 --spatial-beach-limit 50`,
   `--training-window-days 1095`. Commit message claims gate county 0.590 / beach 0.900.
2. **`5d99a8587`** 2026-06-08 19:34 UTC — automated "daily forecast refresh 2026-06-08".
   This is the run that **wrote the current `system_health.json`** — at 12/50, 1095d —
   producing **county 0.499 / beach 0.871**. It did *not* reproduce 0.590/0.900.
3. **`153f1368a`** 2026-06-10 21:53 PDT (≈ "47 min ago" at investigation time) —
   "fix(ci): daily forecast was timing out — trim spatial backtest folds". Drops the
   daily sweep to `--spatial-county-limit 6 --spatial-beach-limit 15` (full 12/50 kept
   only for manual `full_comparison=true`). Bumps job timeout 120 → 170 min.
   **No daily refresh has run since this commit** (`git log` for system_health.json
   ends at `5d99a8587`; the file is clean/unmodified in the working tree).

**Conclusion from the timeline:** the prior investigation's hypothesis ("0.499 came
from the 6/15 shortlist, 0.590 from full 12/50") is **refuted**. Both the 0.499 on
disk *and* the claimed 0.590 are 12/50 / 1095d. The 6/15 trim is a forward-looking
change that has not yet influenced any committed metric. When the next daily run
lands at 6/15, expect the county number to get *noisier* (fewer folds, fewer pooled
rows) — likely staying near ~0.49–0.51, not jumping to 0.590.

---

## Root cause of the offline-vs-gate gap (methodology, not the model)

The model is identical in both paths. `XGBUndersampleEnsemble` defaults
(`app/ml/models.py`: `n_estimators_ensemble=12, negative_ratio=2.0, n_estimators=250,
max_depth=6, learning_rate=0.05`) exactly match the hardcoded params in
`scripts/spatial_compare.py` (`ENSEMBLE_N=12, RATIO=2.0, n_estimators=250,
max_depth=6, learning_rate=0.05`). So the architecture is not the difference.

What differs between the offline `spatial_compare.py` (source of 0.612/0.590-class
numbers) and the in-gate `_spatial_holdout_fold_result`
(`app/ml/training.py:926`, source of the 0.499 on disk):

1. **Calibration.** Offline `_ensemble_predict` returns *raw* soft-averaged XGB
   probabilities and scores AUCPR directly on them (`spatial_compare.py:66-110`).
   The gate applies isotonic calibration to the held-out test probabilities
   (`_identity_or_calibrated` + `_apply_calibrator`, `training.py:1191-1201`).
   Isotonic regression-to-the-mean compresses the score spread and trims ranking
   resolution → lower AUCPR. (Calibration is the *right* thing for a shipped product
   — it is why the disk slope is a healthy 0.99 — but it costs raw AUCPR.)
2. **Inner train/valid split.** Offline fits the ensemble on the *entire* N−1-county
   training set (`spatial_compare.py:95-101`). The gate carves an inner temporal
   `_blocked_indices` split out of the N−1 counties (`training.py:950-956`) and fits
   the model on only the inner-train slice (~70%), reserving inner-valid to fit the
   calibrator. Fewer training rows per fold → weaker fold model.
3. **County selection.** Offline selects the 12 counties with the most *positives*
   (`MIN_TEST_POS=20`, sorted by positive count desc, `spatial_compare.py:87-90`).
   The gate selects the 12 counties with the most *rows*
   (`_eligible_holdout_groups`, `training.py:716-728`: `value_counts()` desc,
   `min_rows>=32`). Different county sets → different pooled base rate and difficulty.
   The disk pooled county positive_rate is **0.175**, a relatively low-positivity mix
   that is intrinsically harder for AUCPR.

The 365d→1095d window genuinely helped (commit's isolation test: offline +marine
0.612 → 0.567 when restricted to 365d), so the window lever is real. But it does
**not** close the offline→gate gap; (1)–(3) do. The gate number is the one that
ships, so the gate number is the one to publish.

---

## Searcy et al. 2018 benchmark — status: NOT reproduced

`CLAUDE.md:165-166` claims: "Searcy et al. 2018 … median sensitivity 0.50 @
specificity 0.87 … Our temporal-holdout hist_gbm: sens 0.59 @ spec 0.87."

- **No code computes sensitivity-at-fixed-specificity** anywhere in the repo
  (`evaluation.py` before this change had only AUCPR / Brier / log-loss /
  calibration-slope / precision@recall). The 0.59 figure has no traceable
  computation.
- **No reusable holdout prediction artifact exists.** `data/curated/` has only
  `forecasts.parquet` (forward forecasts with `p_exceed` but **no ground-truth
  labels**) and the aggregate metrics in `system_health.json`. The per-row
  (label, probability) arrays the gate concatenates are consumed in-memory by
  `classification_metrics` and discarded. So sens@spec0.87 **cannot be recomputed
  without re-running training** to re-derive and persist the holdout predictions.

**Action taken:** added `sensitivity_at_specificity(labels, probs,
target_specificity=0.87)` to `app/ml/evaluation.py`, returning
`{sensitivity, specificity, threshold}`. It picks the threshold that clears the
target specificity while maximizing sensitivity; falls back to the
highest-attainable specificity if the target is unreachable; returns NaN for a
single-class input. Covered by tests in `tests/test_evaluation.py` (perfect
separation, a hand-computed known example, monotonicity in the target, degenerate
single-class). Inline proof on a tiny array:

```
labels = [0,0,0,0, 1,1,1,1]
probs  = [0.1,0.2,0.3,0.4, 0.35,0.6,0.7,0.8]
sensitivity_at_specificity(labels, probs, 0.87) -> sens 0.75 @ spec 1.0 (thr 0.6)
sensitivity_at_specificity(labels, probs, 0.50) -> sens 1.0  @ spec 0.75 (thr 0.35)
```

Until a training run pools and persists holdout predictions, the Searcy "sens 0.59 @
spec 0.87" claim is marked **unverified** in `CLAUDE.md` and here.

**Persistence wired 2026-06-11.** `training.py` now writes the production winner's
held-out (label, probability) pairs to `data/curated/holdout_predictions_temporal.parquet`
(temporal-test rows + `model`/`date`) and `..._spatial.parquet` (pooled county+beach rows +
`model`/`holdout_kind`/`group`), and records `sensitivity_at_specificity(..., 0.87)` into
`system_health.json` under `production_metrics["sensitivity_at_spec_0.87"]` plus the
`spatial_county_<winner>` / `spatial_beach_<winner>` equivalents. After the next daily run
these artifacts exist on disk and the Searcy operating point is a real, citable number —
recompute any other operating point (precision@recall, per-county sensitivity) from the
parquet with no retrain. **Until that run lands the artifacts are absent, so still do not
cite a specific sensitivity value.**

---

## What the published numbers should be

| metric | publish | source |
|---|---|---|
| Held-out **county** AUCPR | **0.499** | system_health.json L82 |
| Held-out **beach** AUCPR | **0.871** | system_health.json L70 |
| County calibration slope | **0.99** | L85 |
| Beach calibration slope | **0.88** | L74 |
| County persistence baseline | **0.370** | L60 |
| County pooled base rate | **0.175** | L68 |
| Searcy sens @ spec 0.87 | **unverified** | not computed; no artifact |

The honest framing: a **0.499 county AUCPR against a 0.175 base rate and a 0.370
persistence baseline is a real but modest spatial lift** — beating persistence by
~0.13 AUCPR on never-seen counties, with near-ideal calibration (slope 0.99). The
beach-level 0.871 is stronger but easier (held-out beaches still get memorable
neighbors and a higher 0.373 base rate). Do not cite 0.590 / 0.900 — those were
never reproduced by the path that actually ships.
