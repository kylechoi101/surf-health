# Metrics Reconciliation — spatial AUCPR gap (docs 0.590 vs gate-real numbers)

**Author:** ML Evaluation & Honesty Engineer
**Date:** 2026-06-10, refreshed 2026-06-11
**Scope:** Why `CLAUDE.md` and commit `93923683d` cited held-out **county AUCPR
0.590 / beach 0.900** that the in-pipeline gate **never reproduced**, what the honest
gate-real numbers are, and the status of the Searcy et al. 2018 benchmark.

> ## ⚠️ These spatial metrics are REGENERATED EVERY DAILY RUN — do not trust the prose
> **`data/curated/system_health.json` (`model_registry.spatial_metrics` +
> `production_metrics`) is the single source of truth.** Every number written in prose
> below is a *snapshot* of the run named beside it and **WILL drift** — the daily sweep
> now uses only **6 county / 15 beach folds** (commit `153f1368a`), so the *pooled*
> AUCPR is noisy run-to-run. Before quoting any figure to a regulator/journalist/partner,
> re-read `system_health.json`. The exact point values here are illustrative of the
> *path and framing*, not a frozen contract.
>
> **Current on-disk snapshot — daily run `c64a0b5da`, 2026-06-11, 6-county / 15-beach
> shortlist @ 1095d** (`public_release_eligible: true`, `promotion_blockers: []`):
>
> | metric | county (folds=6, base rate 0.197) | beach (folds=15, base rate 0.561) | temporal production |
> |---|---|---|---|
> | ensemble AUCPR | **0.553** | **0.932** | **0.750** |
> | hist_gbm AUCPR | 0.481 | 0.928 | — |
> | persistence AUCPR | 0.420 | 0.762 | — |
> | calibration slope | **1.21** | **1.18** | 1.15 |
> | Brier | 0.119 | 0.113 | 0.096 |
> | sensitivity @ spec≈0.87 | **0.482 @ 0.896** | **0.832 @ 0.871** | **0.722 @ 0.871** |

---

## TL;DR

- The gate-computed numbers on disk are the **real, honest generalization metrics** —
  they are what the daily CI gate actually computes on leave-one-county-out /
  leave-one-beach-out holdouts, with production calibration. As of the 2026-06-11 run
  (`c64a0b5da`, 6-county / 15-beach shortlist @ 1095d) they are **county AUCPR 0.553 /
  beach AUCPR 0.932, calib slopes 1.21 / 1.18** (see the snapshot box above). These
  superseded the prior 12/50-fold daily run's **county 0.499 / beach 0.871, slopes
  0.99 / 0.88** — that earlier snapshot is now historical, not the current claim.
  **All of these are snapshots; the live `system_health.json` is authoritative and
  drifts each day** — the 6/15 pooled AUCPR is noisier than the old 12/50 sweep.
- The **0.590 / 0.900** numbers cited in the old docs/commit `93923683d` were
  **never reproduced by the in-pipeline gate**. They are an offline /
  `spatial_compare`-style number or a one-off the committed CI path does not
  regenerate. No `system_health.json` the gate has ever written has shown 0.590/0.900.
- **The 6/15 shortlist trim** (commit `153f1368a`) has now run (`c64a0b5da`,
  2026-06-11). It is expected to make the *pooled* spatial numbers noisier run-to-run
  (fewer folds, fewer pooled rows), not to systematically inflate them. Treat any
  single quoted value as a noisy snapshot.
- The real cause of the offline-vs-gate gap is a **methodology difference between
  the offline `spatial_compare.py` and the in-gate `_spatial_holdout_fold_result`**:
  calibration, an inner train/valid split, and a different county-selection rule.
  Commit `93923683d`'s own message already conceded this ("the rest of the gap is
  the gate's calibration + inner-validation split") — it just didn't update the
  headline number to match.
- **The county AUCPR, over a ~0.20 county pooled base rate and beating the ~0.42
  persistence baseline, is the honest spatial lift.** The beach-level AUCPR is much
  higher (over a ~0.56 base rate where persistence already scores ~0.76) because
  beaches retain memorable per-site base rates even when held out individually — so
  the beach figure sits over a high base rate and the *county* number is the harder,
  more honest test of spatial generalization.
- **Searcy benchmark — now computed (was unreproduced).** A reproducible
  `sensitivity_at_specificity()` helper was added to `evaluation.py`, and
  `training.py` now persists the winner's held-out (label, probability) pairs to
  `data/curated/holdout_predictions_{temporal,spatial}.parquet`. As of the
  2026-06-11 daily run those artifacts EXIST on disk and the operating points are in
  `system_health.json`: leave-one-county-out **sens 0.482 @ spec 0.896** (the honest
  generalization figure, ≈ Searcy 0.50 @ 0.87), temporal-test **0.722 @ 0.871**
  (in-distribution, optimistic). Cite the county number as the conservative real-world
  figure; never a single blended number. The old "0.59 @ 0.87" claim is superseded —
  it matched neither path.

---

## Evidence — the numbers on disk

**CURRENT** (`system_health.json` from daily run `c64a0b5da`, "daily forecast refresh
2026-06-11", file mtime 2026-06-11; 6-county / 15-beach shortlist @ 1095d):

| metric | county (folds=6) | beach (folds=15) |
|---|---|---|
| `spatial_*_xgb_undersample_ensemble` AUCPR | **0.553** | **0.932** |
| Brier | 0.119 | 0.113 |
| calibration_slope | **1.21** | **1.18** |
| precision@80recall | 0.486 | 0.912 |
| pooled positive_rate | **0.197** | 0.561 |
| persistence AUCPR (baseline) | **0.420** | 0.762 |
| sensitivity @ spec≈0.87 | **0.482 @ 0.896** | **0.832 @ 0.871** |

> ⚠️ **Re-read `system_health.json` before quoting these** — they are regenerated by
> every daily run and the 6/15 pooled AUCPR is noisy. The values above are a snapshot
> of run `c64a0b5da` (2026-06-11), not a frozen contract.

**PRIOR (historical, superseded)** — the 12-county / 50-beach daily run `5d99a8587`
("daily forecast refresh 2026-06-08", file mtime 2026-06-09) wrote:

| metric | county (folds=12) | beach (folds=50) |
|---|---|---|
| ensemble AUCPR | 0.4991 | 0.8714 |
| calibration_slope | 0.9873 | 0.8785 |
| persistence AUCPR | 0.3700 | 0.5787 |
| pooled positive_rate | 0.1750 | 0.3734 |

That run used **folds = 12 counties / 50 beaches** (the full shortlist sweep, before
the 6/15 trim). It is kept here only to document the trajectory; **it is no longer the
shipped number** — the 2026-06-11 run above superseded it.

## Evidence — the docs

`CLAUDE.md:150-153`:
> ensemble held-out **county AUCPR 0.507 → 0.590** (Brier 0.118 → 0.107),
> **beach 0.881 → 0.900** … Ensemble passes every gate (calib slopes county 1.26 /
> beach 1.16).

Commit `93923683d` ("feat(ml): train at 1095d window…", 2026-06-08 11:46 PDT)
message repeats the same 0.590 / 0.900 and slopes 1.26 / 1.16.

**The gate-real slopes have never been 1.26 / 1.16.** The 2026-06-08 12/50 run wrote
0.987 / 0.879; the current 2026-06-11 6/15 run writes 1.21 / 1.18. Either way the
1.26/1.16 figure was never reproduced by the path that ships, and slopes near 1.0–1.2
are well-calibrated. So the old docs were optimistic on AUCPR and cited a calibration
story the gate never produced.

---

## Timeline (commit hashes + times)

1. **`93923683d`** 2026-06-08 11:46 PDT — flips CI training window 365 → 1095d.
   Workflow flags at this commit: `--spatial-county-limit 12 --spatial-beach-limit 50`,
   `--training-window-days 1095`. Commit message claims gate county 0.590 / beach 0.900.
2. **`5d99a8587`** 2026-06-08 19:34 UTC — automated "daily forecast refresh 2026-06-08".
   This is the run that **wrote the current `system_health.json`** — at 12/50, 1095d —
   producing **county 0.499 / beach 0.871**. It did *not* reproduce 0.590/0.900.
3. **`153f1368a`** 2026-06-10 21:53 PDT — "fix(ci): daily forecast was timing out —
   trim spatial backtest folds". Drops the daily sweep to `--spatial-county-limit 6
   --spatial-beach-limit 15` (full 12/50 kept only for manual `full_comparison=true`).
   Bumps job timeout 120 → 170 min.
4. **`c64a0b5da`** 2026-06-11 14:20 UTC — automated "daily forecast refresh 2026-06-11",
   the **first daily run at 6/15 / 1095d**. This wrote the **current**
   `system_health.json` — **county AUCPR 0.553 / beach 0.932, slopes 1.21 / 1.18** —
   and, with the holdout-persistence wiring now merged, also wrote the
   `holdout_predictions_{temporal,spatial}.parquet` artifacts and the
   `sensitivity_at_spec_0.87` operating points. It did *not* reproduce 0.590/0.900
   either (no gate run ever has).

**Conclusion from the timeline:** the earlier hypothesis ("0.499 came from the 6/15
shortlist, 0.590 from full 12/50") was **refuted** — both the prior 0.499 *and* the
claimed 0.590 were 12/50 / 1095d. The 6/15 trim has now run (`c64a0b5da`) and produced
**0.553 / 0.932**, confirming the *pooled* spatial AUCPR moves run-to-run (this 6/15
run landed *above* the prior 12/50 run's 0.499, illustrating the run-to-run noise of a
6-fold pooled metric). None of these match the never-reproduced 0.590/0.900. Quote
only the live `system_health.json`, treating any prose figure as a dated snapshot.

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
   — it is why the gate slope is healthy (0.99 on the 12/50 run, 1.21 on the current
   6/15 run) — but it costs raw AUCPR.)
2. **Inner train/valid split.** Offline fits the ensemble on the *entire* N−1-county
   training set (`spatial_compare.py:95-101`). The gate carves an inner temporal
   `_blocked_indices` split out of the N−1 counties (`training.py:950-956`) and fits
   the model on only the inner-train slice (~70%), reserving inner-valid to fit the
   calibrator. Fewer training rows per fold → weaker fold model.
3. **County selection.** Offline selects counties with the most *positives*
   (`MIN_TEST_POS=20`, sorted by positive count desc, `spatial_compare.py:87-90`).
   The gate selects counties with the most *rows*
   (`_eligible_holdout_groups`, `training.py:716-728`: `value_counts()` desc,
   `min_rows>=32`). Different county sets → different pooled base rate and difficulty.
   The current pooled county positive_rate is **~0.20** (0.197 on the 6/15 run; 0.175
   on the prior 12/50 run), a relatively low-positivity mix that is intrinsically
   harder for AUCPR.

The 365d→1095d window genuinely helped (commit's isolation test: offline +marine
0.612 → 0.567 when restricted to 365d), so the window lever is real. But it does
**not** close the offline→gate gap; (1)–(3) do. The gate number is the one that
ships, so the gate number is the one to publish.

---

## Searcy et al. 2018 benchmark — status: now computed (was unreproduced)

The old `CLAUDE.md` claimed: "Searcy et al. 2018 … median sensitivity 0.50 @
specificity 0.87 … Our temporal-holdout hist_gbm: sens 0.59 @ spec 0.87." That 0.59
figure had no traceable computation and was **unverifiable** at the time, because:

- **No code computed sensitivity-at-fixed-specificity** (`evaluation.py` had only
  AUCPR / Brier / log-loss / calibration-slope / precision@recall), and
- **No reusable holdout prediction artifact existed** — the per-row (label,
  probability) arrays the gate concatenated were consumed in-memory by
  `classification_metrics` and discarded.

Both gaps are now closed (see "Action taken" + "Persistence wired" below): a
`sensitivity_at_specificity()` helper was added and the holdout predictions are
persisted. **As of the 2026-06-11 daily run (`c64a0b5da`) the artifacts EXIST on disk**
(`data/curated/holdout_predictions_temporal.parquet`,
`holdout_predictions_spatial.parquet`) and the operating points are recorded in
`system_health.json`, so the benchmark is now a real, recomputable number — the old
0.59 claim is superseded (it matched neither the temporal nor the county path).

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

**Persistence wired 2026-06-11, artifacts now on disk.** `training.py` writes the
production winner's held-out (label, probability) pairs to
`data/curated/holdout_predictions_temporal.parquet` (temporal-test rows + `model`/`date`)
and `..._spatial.parquet` (pooled county+beach rows + `model`/`holdout_kind`/`group`),
and records `sensitivity_at_specificity(..., 0.87)` into `system_health.json` under
`production_metrics["sensitivity_at_spec_0.87"]` plus the `spatial_county_<winner>` /
`spatial_beach_<winner>` equivalents. The 2026-06-11 daily run (`c64a0b5da`) was the
first to carry this wiring, so the artifacts EXIST on disk now and any other operating
point (precision@recall, per-county sensitivity) can be recomputed from the parquet
with no retrain.

**Computed 2026-06-11 (ensemble, daily run `c64a0b5da`) — snapshot, will drift each run:**
| holdout | sensitivity @ spec≈0.87 | threshold | note |
|---|---|---|---|
| Temporal-test | **0.722** @ 0.871 | 0.342 | same beaches in train+test — optimistic, in-distribution |
| Leave-one-county-out | **0.482** @ 0.896 | 0.279 | honest unseen-county generalization ≈ Searcy 0.50 @ 0.87 |
| Leave-one-beach-out | **0.832** @ 0.871 | 0.467 | unseen beach, county signal present; over a ~0.56 base rate |

Cite **~0.48 @ 0.90 (county holdout)** as the conservative real-world figure and
**0.72 @ 0.87 (temporal)** as in-distribution — never a single blended number. The old
"0.59" claim is superseded; it matched neither path. Re-read `system_health.json` for
the live values — these operating points are recomputed every daily run.

---

## What the published numbers should be

> **Always read these from the live `data/curated/system_health.json`** — the table
> below is a snapshot of daily run `c64a0b5da` (2026-06-11) and WILL drift; the 6/15
> pooled AUCPR is noisy run-to-run.

| metric | publish (2026-06-11 snapshot) | source key |
|---|---|---|
| Held-out **county** AUCPR | **0.553** | `spatial_metrics.spatial_county_xgb_undersample_ensemble.aucpr` |
| Held-out **beach** AUCPR | **0.932** | `spatial_metrics.spatial_beach_xgb_undersample_ensemble.aucpr` |
| County calibration slope | **1.21** | `…spatial_county_…calibration_slope` |
| Beach calibration slope | **1.18** | `…spatial_beach_…calibration_slope` |
| County persistence baseline | **0.420** | `spatial_county_persistence.aucpr` |
| County pooled base rate | **0.197** | `…spatial_county_…positive_rate` |
| Beach pooled base rate | **0.561** | `…spatial_beach_…positive_rate` |
| Temporal production AUCPR | **0.750** | `production_metrics.aucpr` |
| Searcy sens @ spec 0.87 (county) | **0.482 @ 0.896** | `…spatial_county_…sensitivity_at_spec_0.87` |
| Searcy sens @ spec 0.87 (temporal) | **0.722 @ 0.871** | `production_metrics.sensitivity_at_spec_0.87` |

The honest framing: a **county AUCPR (~0.55) against a ~0.20 base rate and a ~0.42
persistence baseline is a real spatial lift** — beating persistence by ~0.13 AUCPR on
never-seen counties, with well-controlled calibration. The beach-level AUCPR (~0.93) is
higher but easier: held-out beaches still get memorable neighbors and the beach holdout
**sits over a high ~0.56 base rate where persistence already scores ~0.76**, so the
beach figure overstates difficulty. The county number is the harder, more honest test.
The temporal production AUCPR (~0.75) is **in-distribution-inflated** (same beaches in
train+test) and is not a generalization claim. Do not cite 0.590 / 0.900 — those were
**never reproduced** by the path that actually ships. Every figure here is a dated
snapshot; the live `system_health.json` is the single source of truth.
