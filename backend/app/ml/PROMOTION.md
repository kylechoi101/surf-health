# Promotion rule for the served estimate

Committed 2026-10-02, **before** any run of `scripts/compare_all_models.py`, so the result
cannot shape the rule (`docs/UPDATE_PLAN.md` step 2.1). Changing this file after a comparison
has been read requires a dated entry under "Amendments" saying what changed and why, and the
comparison must be re-run under the amended rule.

## The rule

A challenger replaces the served estimate only if **all** of the following hold.

1. **Population.** Forward outcomes: for each (beach, forecast day D) in the walk-forward
   window, the label is the first enterococcus sample at that beach in D+1..D+3
   (`compare_logit_challenger.forward_pairs`). Every arm is scored on the same pairs, with
   the same persistence floor applied (a beach whose last sample exceeded is never below
   `_LOW_THRESHOLD`), and with features built strictly from data dated before D.
2. **Metrics that decide.** Within-beach AUROC (row-weighted mean of per-beach AUROC, beaches
   with both outcomes only) and Brier score.
3. **Margin.** For **each** of the two metrics, the beach-cluster bootstrap 95% CI of
   (challenger − served) excludes 0 in the challenger's favour: within-beach AUROC delta CI
   entirely above 0, Brier delta CI entirely below 0. Resampling unit = beach; at least 300
   replicates; same seed for every arm.
4. **Slices.** Condition 3 holds on **both** the all-beach slice and the non-San-Diego slice.
   (San Diego is a different labelling universe — ddPCR judged at 1413 copies — and supplies
   most positives; a win that exists only there is not a win for the product.)
5. **Ties go to the simpler model.** Simplicity order: `pooled` < `persistence` < `lookup` <
   `logit` < `logit_method` < `xgb_ensemble` < `xgb_offset`. If two challengers both pass,
   the simpler one is promoted unless the more complex one also passes condition 3 against
   the simpler one.

AUROC, AUCPR, log loss and sensitivity at specificity 0.87 are **reported but do not
decide**. Global AUROC/AUCPR mostly measure "knows which beaches are dirty", not daily
skill, and AUCPR moves with the base rate of whatever population is scored (CLAUDE.md,
"The measurement gap").

## What passing buys

- `logit_method` passing: the term is adopted into the served logistic (UPDATE_PLAN 2.6).
- An XGB arm passing: it may serve only through the existing router/fallback machinery,
  after a 2-week shadow period on the live scoreboard (UPDATE_PLAN 3.1) in which the live
  forward within-beach AUROC and Brier deltas keep the same sign.
- Nothing passing: the served estimate is unchanged. That is a valid outcome, not a failure.

## Reporting obligations

The comparison report must show, per arm and slice, every metric above with its bootstrap
CI, the number of pairs and beaches, and the realized exceedance rate per served risk band.
When the before/after data snapshots serve different beach sets, report on common pairs,
full pairs, and new-beach pairs separately (UPDATE_PLAN 2.5); the decision is taken on the
**after** snapshot's full pairs, and must not reverse on its common pairs.

## Amendments

(none)
