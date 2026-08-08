# 5 — How effective is the model, by county and by beach?

Everything here is computed from artifacts committed in `data/curated/` at pipeline run
`2026-08-02T00:37:54Z`. Reproduce with the script in
[§ 5.7](#57-reproducing-these-numbers).

**Companion visualization:**
[Model effectiveness by county and beach](https://claude.ai/code/artifact/eceb160a-a2c3-4d56-8698-d2a87621ce6a)
renders every table below as charts, with the data tables inline.

---

## 5.1 Read this first: there are two different questions

The repo scores itself in two regimes that are **not comparable to each other**, and
confusing them is how every optimistic claim about this system has historically been
made.

| | **Backtest** | **Served** |
|---|---|---|
| Source | `holdout_predictions_spatial.parquet` | `forecast_history.parquet` ⋈ `observations.parquet` |
| Rows scored | Sample-days only | Every published forecast that later got a lab result |
| Feature freshness | Lagged history is fresh (a sample was taken that morning) | Median ~9 days stale |
| Question answered | *Can it generalise to a place it never trained on?* | *Was the thing we published right?* |
| Population base rate | 0.204 (county folds) / 0.582 (beach folds) | 0.082 |

Two consequences that must be held in mind for every number below:

**AUCPR is base-rate dependent; AUROC is not.** Measured directly by diluting a fixed
set of predictions, AUCPR falls 0.532 → 0.322 with the model, ranking, and all else held
constant, while AUROC stays flat at ~0.772. The eval and serve populations differ ~3× in
base rate, so **~71% of the apparent "backtest 0.65 → served 0.28" AUCPR collapse is
arithmetic, not skill loss.** Compare AUROC across populations; only ever compare AUCPR
against its own no-skill floor (the base rate), which is why every table here carries
`aucpr_lift = aucpr / base_rate`.

**Global AUROC is dominated by between-beach variance.** A model scores well by knowing
Imperial Beach is dirtier than Carmel, with zero ability to tell Tuesday from Thursday at
either. § 5.5 is the metric that separates the two, and it is the least flattering
section in this document.

---

## 5.2 Backtest — leave-one-county-out (6 folds, 69,880 held-out rows)

Train on 5 counties, predict the 6th, rotate. Production winner
`xgb_undersample_ensemble`; persistence = "predict whatever happened last time."

| County | n | Base rate | **AUROC** | AUCPR | Lift | Brier | vs flat | Sens @ spec 0.87 |
|---|---:|---:|---:|---:|---:|---:|:--:|---:|
| Ventura | 3,487 | 0.045 | **0.870** | 0.420 | 9.39× | 0.033 | ✔ | 0.699 |
| San Francisco | 3,051 | 0.131 | **0.850** | 0.518 | 3.95× | 0.085 | ✔ | 0.668 |
| Los Angeles | 19,023 | 0.164 | **0.844** | 0.566 | 3.46× | 0.113 | ✔ | 0.560 |
| San Diego | 20,989 | 0.416 | **0.833** | 0.717 | 1.72× | 0.185 | ✔ | 0.425 |
| San Mateo | 3,435 | 0.214 | **0.823** | 0.545 | 2.55× | 0.148 | ✔ | 0.525 |
| Orange | 19,895 | 0.056 | **0.797** | 0.276 | 4.90× | 0.047 | ✔ | 0.569 |
| **Pooled** | **69,880** | **0.204** | **0.887** | **0.648** | **3.18×** | **0.112** | ✔ | **0.738** |
| *Persistence (pooled)* | 69,880 | 0.204 | *0.787* | *0.503* | *2.46×* | *0.140* | ✔ | *0.663* |

**Every county beats persistence and beats a flat base-rate constant.** The spread is
tight (0.797–0.870), which is the encouraging part: the model does not depend on having
seen a county before.

Note the pooled AUROC (0.887) exceeds every individual county's. That is not an error —
pooling adds between-county separation the per-fold numbers deliberately exclude. It is
also a small demonstration of why the pooled figure flatters.

The cluster-bootstrap 95% CI on the pooled county AUCPR is **[0.378, 0.705]**. Resampling
at the fold level, not the row level, because rows within a held-out county are not
independent. Any claimed improvement smaller than ~0.14 AUCPR is inside the noise.

---

## 5.3 Backtest — leave-one-beach-out (15 folds, 12,238 held-out rows)

| Beach (station) | County | n | Base | **AUROC** | AUCPR | Lift | Sens@.87 |
|---|---|---:|---:|---:|---:|---:|---:|
| Imperial Beach Pier | SD | 963 | 0.968 | **0.965** | 0.998 | 1.03× | 0.843 |
| Santa Monica — Ashland storm drain | LA | 724 | 0.080 | **0.957** | 0.778 | 9.71× | 0.879 |
| Imperial Beach pier area — Date Ave | SD | 777 | 0.960 | **0.952** | 0.997 | 1.04× | 0.806 |
| Manhattan Beach — 28th St storm drain | LA | 709 | 0.083 | **0.926** | 0.660 | 7.93× | 0.814 |
| Will Rogers — Santa Monica Canyon | LA | 718 | 0.266 | **0.923** | 0.831 | 3.12× | 0.827 |
| Imperial Beach — Cortez Ave | SD | 861 | 0.965 | **0.920** | 0.995 | 1.03× | 0.740 |
| north Imperial Beach — Carnation Ave | SD | 953 | 0.942 | **0.917** | 0.992 | 1.05× | 0.834 |
| Silver Strand — Guard Shack | SD | 966 | 0.812 | **0.903** | 0.969 | 1.19× | 0.787 |
| Coronado City — Avenida Lunar | SD | 966 | 0.645 | **0.879** | 0.923 | 1.43× | 0.713 |
| Imperial Beach — End of Seacoast Dr | SD | 856 | 0.954 | **0.827** | 0.985 | 1.03× | 0.496 |
| Inner Cabrillo — CB-01 | LA | 725 | 0.168 | **0.761** | 0.511 | 3.03× | 0.484 |
| Topanga Beach | LA | 708 | 0.280 | **0.730** | 0.596 | 2.13× | 0.455 |
| Marina Del Rey — Playground | LA | 867 | 0.262 | **0.710** | 0.535 | 2.04× | 0.379 |
| Santa Monica Pier | LA | 721 | 0.499 | **0.697** | 0.693 | 1.39× | 0.322 |
| Inner Cabrillo — CB-02 | LA | 724 | 0.390 | **0.695** | 0.605 | 1.55× | 0.301 |
| **Pooled** | | **12,238** | **0.582** | **0.940** | **0.960** | **1.65×** | **0.870** |
| *Persistence* | | 12,238 | 0.582 | *0.838* | *0.826* | *1.42×* | *0.000* |

**The pooled 0.960 AUCPR is the most misleading number in the repo, and the table shows
why.** The fold selection picks beaches by row count, which selects chronically polluted
Tijuana-plume stations — seven of the fifteen have a base rate above 0.8. At a 96.8% base
rate, "always say yes" scores 0.968 AUCPR. The *lift* column strips this out: those
stations score 1.03×, i.e. almost nothing above the floor, while Manhattan Beach's storm
drain at an 8.3% base rate scores **7.93×** — that is where real skill lives.

Persistence's sensitivity of **0.000** at specificity 0.87 is not a bug. Its predictions
are a two-valued step function {0, 1}, so no threshold exists that achieves 87%
specificity without also rejecting every positive. It is a genuine limitation of the
baseline, and a good argument for why a probabilistic model is worth having at all.

---

## 5.4 Served — the deployment truth (13,091 scoreable pairs, 542 beaches)

Every forecast actually published between **2026-04-23 and 2026-07-30**, matched to the
lab result that arrived on the same day or in D+1…D+3.

**Only 47% of published forecasts ever became checkable.** The rest were published on
days nobody sampled — which is the product's whole reason to exist and simultaneously the
reason it can never be fully graded.

| County | n | Base rate | **AUROC** | AUCPR | Lift | Brier | Beats flat? | Bias |
|---|---:|---:|---:|---:|---:|---:|:--:|---:|
| San Diego | 2,869 | 0.183 | **0.834** | 0.585 | 3.19× | 0.115 | ✔ | −0.051 |
| San Francisco | 377 | 0.011 | **0.819** | 0.035 | 3.25× | 0.013 | ✘ | +0.034 |
| Monterey | 119 | 0.034 | **0.813** | 0.123 | 3.66× | 0.032 | ✔ | −0.006 |
| Santa Cruz | 686 | 0.055 | **0.724** | 0.131 | 2.37× | 0.059 | ✘ | +0.028 |
| San Luis Obispo | 784 | 0.019 | **0.713** | 0.053 | 2.79× | 0.031 | ✘ | +0.029 |
| San Mateo | 1,040 | 0.144 | **0.708** | 0.283 | 1.96× | 0.151 | ✘ | +0.084 |
| Los Angeles | 1,599 | 0.100 | **0.696** | 0.199 | 1.98× | 0.123 | ✘ | +0.070 |
| Orange | 1,337 | 0.045 | **0.658** | 0.079 | 1.77× | 0.049 | ✘ | +0.034 |
| Marin | 758 | 0.037 | **0.642** | 0.086 | 2.32× | 0.065 | ✘ | +0.072 |
| Santa Barbara | 759 | 0.038 | **0.604** | 0.058 | 1.52× | 0.047 | ✘ | +0.029 |
| Ventura | 1,849 | 0.007 | **0.585** | 0.009 | 1.43× | 0.012 | ✘ | +0.029 |
| East Bay Parks | 328 | 0.137 | **0.521** | 0.168 | 1.22× | 0.163 | ✘ | +0.014 |
| **Mendocino** | 230 | 0.030 | **0.375** | 0.026 | **0.87×** | 0.065 | ✘ | +0.034 |
| **Pooled** | **13,091** | **0.082** | **0.781** | **0.279** | **3.39×** | **0.0763** | **✘** | **+0.023** |

Four honest readings:

1. **Ranking skill survives deployment. Calibration mostly does not.** Pooled AUROC 0.781
   served vs 0.887 backtest — a real but modest drop. Yet the pooled Brier (0.0763)
   **loses to a flat base-rate constant** (0.0756), and it loses in 11 of 13 counties. The
   model knows which beaches and days are riskier; it is systematically over-confident
   about how much.

2. **The bias is one-signed.** Twelve of thirteen counties have a **positive** bias — the
   model over-predicts risk. Every county except San Diego and Monterey warns more than
   reality warrants. For a public-health product this is the safer direction to be wrong,
   but it is the direction that erodes trust fastest.

3. **Mendocino is below chance (AUROC 0.375, lift 0.87×).** With 230 pairs and 7
   positives this is thin evidence, but it is not noise around 0.5 — it is consistently
   the wrong direction. Mendocino has no first-class scraper and falls back to BeachWatch.
   It should be a candidate for demotion to `support_status = beta` until investigated.

4. **The counties where the model looks worst are the low-base-rate ones.** Ventura
   (0.65% base rate) at AUROC 0.585 has 12 positives in 1,849 rows. Very little is
   learnable there, and the honest product answer may be "this county has almost no
   exceedances" rather than a daily probability.

### The two-tier router already fixed the calibration failure

The router went live 2026-07-22. Splitting the served window on that date:

| Window | n | **AUROC** | AUCPR | Brier | Flat Brier | Beats flat? | Bias |
|---|---:|---:|---:|---:|---:|:--:|---:|
| Pre-router (04-23 → 07-21) | 12,421 | 0.781 | 0.278 | 0.0767 | 0.0753 | ✘ | **+0.025** |
| **Post-router (07-22 → 07-30)** | **670** | **0.814** | **0.340** | **0.0682** | **0.0815** | **✔** | **−0.007** |

Post-router the Brier **beats the flat baseline**, the bias collapses from +0.025 to
−0.007, and sensitivity at spec 0.87 rises 0.537 → 0.650. That is the level+deviation
model doing exactly what its docstring predicted.

⚠️ **670 pairs over 9 days is a small sample and the two windows are different seasons.**
Treat this as a promising early signal, not a proven improvement — the honest test is to
re-run this split once the post-router window has 90 days in it. The `served_metrics`
block in `system_health.json` will show it automatically as the window rolls forward.

---

## 5.5 The uncomfortable number: within-beach daily skill

Everything above measures whether the model can tell *beaches* apart. The product's
actual promise is telling *days* apart at the beach you are standing on.

`two_tier.within_beach_auroc` computes AUROC separately inside each beach, then
row-weights. On served forecasts, over the 77 beaches with ≥20 scoreable days:

> ## **0.485**
> **Within-beach AUROC across 77 beaches / 4,069 scored days. 0.50 = no skill.**

| County | Within-beach AUROC | Beaches | Rows |
|---|---:|---:|---:|
| San Luis Obispo | **0.588** | 4 | 208 |
| San Francisco | **0.540** | 1 | 26 |
| San Diego | **0.540** | 20 | 1,240 |
| Los Angeles | **0.510** | 11 | 701 |
| Santa Barbara | 0.482 | 4 | 230 |
| San Mateo | 0.453 | 14 | 626 |
| East Bay Parks | 0.431 | 8 | 318 |
| Marin | 0.419 | 5 | 174 |
| Ventura | 0.401 | 3 | 163 |
| Santa Cruz | 0.375 | 5 | 291 |
| Mendocino | 0.330 | 2 | 92 |

**At a fixed beach, the served forecast cannot currently rank that beach's contaminated
days above its clean days.** Only four counties clear 0.50, and the best is 0.588.

This does not mean the product is useless — a 0.781 global AUROC is real information
about *which beaches* carry more risk, and the risk-band UI is largely consumed that way.
But it does mean the day-to-day movement in the band is not yet carrying verified signal,
and nothing in this repo should claim otherwise.

Three things make this measurement honest rather than alarmist:

- It is computed by the repo's own shipped function, not a bespoke script.
- The **backtest** equivalent is **0.855** (leave-one-beach-out), and on the
  censored/stale regime the offset model holds **0.819** while the ensemble drops to
  **0.694** and hist_gbm to 0.682 (`two_tier_diagnostics.spatial_beach_stale_by_model`).
  So the metric works and the models can score well on it — the gap is the serving
  regime, not a broken measurement.
- 77 of 542 beaches qualify (≥20 scoreable days, both classes present). The rest are
  sampled too sparsely to compute per-beach AUROC at all — which is the measurement gap
  restated.

### The label-free counter-evidence

One check needs no daily ground truth: does the predicted series *move* like reality?
Recomputed over 25,696 consecutive-day pairs in `forecast_history.parquet`, the risk band
changes on **5.6%** of beach-days, and **90.7% of those changes occur on days with no new
lab sample** — so the model is responding to rain/solar/wind covariates rather than
parroting the last lab result. Necessary but not sufficient: correct variance is not
correct timing.

*(`CLAUDE.md` records 6.49% / 92.5% from an earlier run; the figures above are recomputed
from the current committed artifacts and supersede them.)*

---

## 5.6 Reliability and staleness

### Reliability — trustworthy below 0.3, hot above it

| Predicted range | n | Mean predicted | Actual rate |
|---|---:|---:|---:|
| 0.00 – 0.02 | 4,220 | 0.011 | 0.021 |
| 0.02 – 0.05 | 3,700 | 0.032 | 0.043 |
| 0.05 – 0.10 | 1,885 | 0.067 | **0.068** |
| 0.10 – 0.20 | 1,197 | 0.139 | 0.104 |
| 0.20 – 0.30 | 668 | 0.220 | 0.195 |
| 0.30 – 0.50 | 851 | 0.337 | 0.250 |
| 0.50 – 0.70 | 165 | 0.589 | 0.236 |
| **0.70 – 1.00** | **405** | **0.974** | **0.477** |

Below 0.30 — where ~90% of served rows live — the model is well calibrated, slightly
*under*-predicting at the very bottom (safe direction). Above 0.5 it is roughly 2×
over-confident: rows predicted at 0.97 realise 0.48.

Those high bins are almost entirely **pre-router persistence-pinned rows**. Rows at
`p_exceed = 1.0` ran 2.39% of the 90-day window (612 rows, realising ~31%) and have been
**zero since 2026-07-22**, along with everything ≥ 0.7. The router removed the pin.

The daily isotonic serving refit is the second line of defence, and it currently works:
**Brier 0.0783 → 0.0670 against a flat base rate of 0.0756** (13,091 pairs, 1,079
positives). Because the map is monotone, AUROC is untouched.

### Skill vs sample age — the train/serve gap, measured

| Days since last lab sample | n | Base rate | **AUROC** | Lift | Beats flat? |
|---|---:|---:|---:|---:|:--:|
| 2–3 d | 148 | 0.196 | **0.852** | 2.62× | ✔ |
| 4–7 d | 2,771 | 0.055 | **0.768** | 3.43× | ✘ |
| 8–14 d | 1,912 | 0.059 | **0.681** | 2.36× | ✘ |
| 15–30 d | 3,089 | 0.106 | **0.805** | 3.70× | ✔ |
| 31 d+ | 1,544 | 0.086 | **0.806** | 4.12× | ✔ |

The expected monotonic decay appears from 2–3 d (0.852) to 8–14 d (0.681) and then
**reverses**. That is not the model recovering at 30 days; it is composition. Beaches
sampled monthly are disproportionately the chronically-polluted or chronically-clean ones
where between-beach separation carries the AUROC. It is a clean illustration of why
per-beach conditioning (§ 5.5) is the metric that matters, and a reminder that any
aggregate stratified by a variable correlated with beach identity will mislead.

---

## 5.7 Reproducing these numbers

```bash
cd /Users/kylechoi/surf_health
backend/.venv/bin/python docs/walkthrough/eval_by_geo.py
```

The script (committed alongside this document) reads only files already in
`data/curated/` and takes ~20 s. It recomputes every table above plus the JSON the
visualization embeds.

**Do not cite any number in this document as current.** The spatial folds are
regenerated every daily run at 6 counties / 15 beaches, so the pooled AUCPR is noisy
run-to-run. The live values are:

- `data/curated/system_health.json` → `model_registry.spatial_metrics` (backtest)
- `data/curated/system_health.json` → `served_metrics` (deployment)
- `data/curated/system_health.json` → `model_registry.metrics.two_tier_diagnostics`
  (within-beach skill and the router split — note the nesting)

And remember: **`production_model` names the registry *winner*, not the model that
computed `p_exceed`.** Read `served_offset_weight` in `forecast_history.parquet`
(0 = ensemble, 1 = offset) to know what actually produced a given row.

---

## 5.8 What to do next, in priority order

1. **Wait for 90 post-router days, then re-run § 5.4.** The single highest-value action is
   patience: the router's apparent calibration fix rests on 670 pairs. `served_metrics`
   will report it automatically.
2. **Split `served_metrics` by `served_offset_weight`.** Right now the published 90-day
   window straddles the cutover and averages two different models, understating what is
   running. This is a small change in `served_metrics._score`.
3. **Investigate Mendocino (AUROC 0.375) and East Bay Parks (0.521).** Both lack
   first-class scrapers. Demote to `beta` support status until they clear 0.5.
4. **Build the daily-cadence evaluation.** **51 beaches** sample at a median gap ≤ 2 days,
   giving **46,480 consecutive-day label pairs** where the outcome flips **15.3%** of the
   time — versus **41.5%** under independence at the same 29.4% base rate. Strongly
   autocorrelated but far from static, so interpolating between weekly samples is
   structurally wrong. Those beaches are unrepresentative (base rate 0.294 vs 0.082
   served), but they are the only place daily skill is falsifiable today, and a model that
   cannot beat persistence *there* cannot be trusted on a weekly-sampled beach. Build:
   retrospective daily grid per candidate → within-beach AUROC by lead time 1–7 vs
   persistence, plus a flip-day readout.

   *(`CLAUDE.md` records 37 beaches / 3,188 pairs / 19.4% from an earlier run; the figures
   above are recomputed from the current committed artifacts.)*
5. **Consider suppressing daily band movement where within-beach AUROC < 0.5.** If the
   day-to-day signal is not verified at a beach, showing a changing band each morning
   implies a precision the model has not earned. A stable band plus "last sampled N days
   ago" may be the more honest UI.
