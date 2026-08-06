# Two assays, one label: culture vs ddPCR enterococcus

**Status: OPEN.** Nothing here is fixed in code. This documents a measured
property of the data that affects the training label, the evaluation metrics,
and the served forecast. Written 2026-08-06.

> **The one-line version.** California judges beach water by enterococcus, but
> two lab methods with two thresholds both write into a single `exceeds_stv`
> column. On paired samples of the same water they agree **50.6%** of the time.
> The threshold is not the bug and must not be changed. The disagreement is
> almost entirely a function of **where the beach is**, not what the weather did.

---

## 1. The two rules

| | method | unit | threshold |
|---|---|---|---|
| Culture | Enterolert, EPA 1600, membrane filtration | MPN or CFU / 100 mL | **> 104** |
| Molecular | San Diego `MCB-ddPCR SOP018-000` (formerly `ddPCR`) | copies / 100 mL | **> 1413** |

Both are applied correctly by `app/data/pipeline/exceedance.py::compute_exceeds_stv`.
Both write `exceeds_stv`. That column is:

- the **training label** (`ml/training.py`)
- the **persistence signal** at serve time, via `exceeds_stv_last_obs`
- the **promotion-gate baseline** every model is scored against
- the **ground truth** `served_metrics` scores the shipped forecast against

## 2. How much they disagree

**1,175 same-beach, same-day pairs** where both methods ran:

```
agreement                50.6%
culture flags            12.2%
PCR flags                60.3%
PCR flags alone          48.8%
culture flags alone       0.6%

median culture value        10 MPN     (threshold 104)
median ddPCR value       2,240 copies  (threshold 1413)
```

The 1413 threshold sits **below the median ddPCR reading**, so more than half of
all molecular samples are automatically an exceedance. Stable across five years
(culture 0.046–0.168, PCR 0.517–0.681), so it is not a transient calibration
drift.

## 3. 1413 is correct — do not change it

It is **not** a misapplied EPA figure. EPA's qPCR Beach Action Value is 1000
CCE/100 mL for Method 1611. 1413 is a **CDPH-developed value fitted directly
against raw ddPCR copies**:

- Crain et al. (2021) built an "intrinsic copy number equation" (ICE) from split
  samples at **51 San Diego County beach sites** — training N=185, test N=1,086.
  *"The ICE was used to propose a new ddPCR-based BAV of 1413 copies/100 mL."*
- US EPA Region 9 approval **2020-10-06**, as a California pilot program.
- CDPH authorization under H&SC §115880(d).
- In use *"since May 5, 2022"* — which matches our data to the day.

**San Diego DEH uses 1413 to issue the Bacterial Exceedance Advisories this
product exists to predict.** Changing it would make our labels agree better with
culture and *worse* with what the public is actually told.

### Why the county adopted it

From Verbyla & Lacarra (2026), quoting the rationale:

- **Speed.** *"Culture-based methods also require overnight incubations, so
  results are not obtained until the day after samples are collected, but with
  PCR-based methods, results can be obtained a few hours after sample
  collection, facilitating more timely beach management decisions."*
- **Method quality.** Digital PCR offers *"greater sensitivity, higher
  precision, and less impact from inhibitors"* than qPCR.
- **Regulatory route.** No dPCR method is EPA-standardized; it runs under EPA's
  alternative-method allowance, which requires *"a consistent and predictable
  relationship with the original method."*

## 4. What the literature says

**Verbyla & Lacarra, *J. Microbiol. Methods* 240:107346 (Jan 2026)** — Coronado,
3 beaches, daily sampling, summer 2023. **PDF read directly 2026-08-06**; the
figures below are from the primary source, not a search snippet.

- **The method fails EPA's own comparability criteria at those beaches.** The
  paper quotes US EPA (2014): *"An IA value of 0.70 or greater demonstrates
  acceptable equivalence…; if IA is less than 0.70, then an R² value of at least
  0.60 demonstrates acceptable equivalence."* Measured at Coronado: **IA = 0.25**
  and **R² = 0.41**. Neither gate is met, so by that rule ddPCR there qualifies
  for neither the same numerical limits nor regression-derived new ones.
  ⚠️ Scope: three beaches, one summer. The EPA approval rests on Crain's
  county-wide N=1,993, not on this.
- **56.3% ddPCR false-positive rate** against the Enterolert action value. Our
  independent 48.8% PCR-flags-alone rate reproduces it on a different corpus.
- **Their descriptives mirror ours.** Coronado ddPCR median **1,669** copies and
  geometric mean **3,101** — *both above the 1413 BAV* — while Enterolert median
  7.8 MPN and geomean 18.0 sit "well below" 104.
- **The conversion is not portable.** The ICE fitted on Coronado data has slope
  **0.00385** against the county-wide ICE's **0.06183** — ~16× shallower at one
  location than the relationship 1413 is derived from. Their log-transformed
  slope 0.5151 is close to our log-log 0.637; both far below 1, i.e. **no
  constant conversion factor exists**.
- **Mechanism, in the paper's words:** *"PCR-based methods can detect free DNA
  and DNA from dead cells or non-culturable cells, in addition to the DNA from
  culturable cells, while culture-based methods only detect culturable cells."*

> ⚠️ **A CORRIGENDUM exists** — *J. Microbiol. Methods* 244:107453, May 2026 —
> and has **not** been read. Do not treat the figures above as final until
> someone checks what it revises.

## 5. What actually drives the discordance (our analysis)

Restricting to the **1,032 pairs where culture says CLEAN**, and asking what
predicts PCR flagging (55.5% of them do).

### 5.1 It is not threshold margin

| | median PCR | 75th pct | max |
|---|---|---|---|
| PCR also clean (n=459) | 509 | 888 | 1,405 |
| **PCR flags (n=573)** | **6,259** | 24,623 | 1.6M |

Only 29% of discordant rows sit within 2× of the threshold; **34% are more than
10× over it**. Where the methods disagree, PCR reads enormously high.

### 5.2 Antecedent environmental conditions explain ~nothing

Pooled **within-beach** effect (beach identity controlled), rank-biserial:

```
salinity_psu            -0.144      fresher water -> flags
water_temperature_c     -0.107
precip_awi              +0.067
precip_mm_7d            +0.039
streamflow_cfs_latest   +0.025
wave_height_m           +0.017
precip_mm_24h           +0.016
precip_mm_72h           +0.005      rainfall: zero
```

**Rainfall does not drive it.** The "DNA persists after runoff" hypothesis is not
supported. The largest within-beach signals (antecedent wetness +0.137, salinity
−0.122 at mid-gradient beaches) point weakly at freshwater input and explain
very little.

### 5.3 Location explains almost everything

```
beach                                flag rate   km from TJ River   median PCR
Imperial Beach municipal               0.947           1.6            19,566
North Imperial Beach                   0.882           3.6             8,925
Silver Strand ib-069                   0.775           8.8             3,212
Silver Strand ib-070                   0.734           9.3             2,551
Coronado North                         0.653          16.0             2,342
Dog Beach OB                           0.450          25.5             1,182
La Jolla Shores                        0.176          35.8               697
Torrey Pines State                     0.069          44.2               375
Buccaneer Beach                        0.057          72.9               246
```

- **Spearman(per-beach flag rate, distance to Tijuana River mouth) = −0.916.**
- Distance to *any* estuary is weaker (−0.804), so it is the Tijuana plume
  specifically, not estuaries generally. Dog Beach is the tell: 0.3 km from the
  San Diego River mouth but 25 km from Tijuana, and it flags at only 45%.
- Row-level Spearman(ddPCR value, distance to Tijuana) = −0.661.

### 5.4 It is not episodic

Day-over-day flip rate vs what independence predicts:

```
Coronado North      0.444  vs  0.453
Silver Strand       0.361  vs  0.349
San Dieguito        0.333  vs  0.352
San Diego Bay       0.356  vs  0.485
```

Within a beach, whether PCR flags on a given day is close to a coin flip
weighted by that beach's baseline rate. **No signature of discrete contamination
events.**

### 5.5 The photo-inactivation hypothesis is untestable here

Solar/wind covariates only exist from 2026 — **7% of paired rows, n=56**. Every
effect is null (uv_index +0.007 p=0.97; solar_inactivation −0.048 p=0.78;
shore-normal wind −0.292 p=0.078 is the closest to anything). Testing it
properly needs a solar-wind backfill over 2022–2025.

## 6. Interpretation: neither assay is simply "wrong"

The pattern — fixed by location, unrelated to weather, non-episodic, PCR reading
10× over threshold while culture reads clean — is the signature of a **chronic
continuous source**, not of transient conditions.

- **Near the Tijuana plume**, median ddPCR is 19,565 copies against a *permanent*
  closure. Calling that a false positive is probably wrong; culture is more
  likely failing to recover viable-but-nonculturable organisms in
  sewage-impacted water.
- **At mid-gradient beaches** — Coronado North 65%, San Diego Bay 41% — culture
  almost never flags and postings are rare. There ddPCR looks genuinely hot.

The truth is site-dependent, which is exactly what the −0.916 gradient says, and
why a single county-wide conversion cannot hold.

## 7. What it does to the product

On the live 1095-day training window:

```
ddPCR is  15.3% of enterococcus rows
ddPCR is  51.9% of all POSITIVE LABELS

exceedance rate   culture 0.0992   PCR 0.5910    (6.0x)

San Diego is 26.0% of rows, 57.6% of positives
base rate: San Diego 0.386  |  rest of California 0.100

dropping ddPCR rows: -15.3% of rows, -51.9% of positives,
base rate 0.1745 -> 0.0992
```

- **Training.** Over half the positive signal comes from a regime 14 of 15
  counties do not use.
- **Evaluation.** Leave-one-county-out with San Diego held out is not a spatial
  generalization test — it holds out a *different labelling universe* at 3.9× the
  base rate. Plausibly why county-holdout AUCPR (~0.55) and beach-holdout
  (~0.93) diverge so far.
- **Serving.** `exceeds_stv_last_obs` drives the persistence floor, and the
  anchor assay is not stable: over the 180 days ending at the latest sample,
  **18 beaches changed anchor assay 311 times** (one of them 34 times in 46
  samples). The exact count shifts with the window definition; the shape does
  not. All 43 rows in the serving
  calibrator's `y ≥ 0.70` region are San Diego, so the top of the published
  probability scale is defined entirely by ddPCR-labelled outcomes.

### Assay history per beach (all history)

Of 90 beaches that ever reported PCR — 87 San Diego, 3 Mendocino (a units-field
error, see §10):

| pattern | n |
|---|---|
| dual (culture continues alongside PCR) | 55 |
| **switched** (culture stopped before PCR began) | **29** |
| PCR-only, no culture history | 6 |

San Diego **added** ddPCR on 2022-05-05 and runs both to this day (~55–65% PCR
share, culture still at 62–65 beaches/month). At the *station* level 29 beaches
genuinely switched, with dates spanning 2022-05 → **2026-01** — the boundary is
still moving, and 49 beaches carry both assays inside the current training
window.

## 8. What to do — in order

1. **Do NOT change 1413.** It is the operative regulatory rule.
2. **Carry `is_pcr` / `label_method` into `beach_day.parquet`.** It is dropped
   there today, which is the root of the whole method-blind feature class:
   `enterococcus_value_lag_*`, `enterococcus_value_last_obs`, `log_enterococcus`,
   and the 35/104-thresholded geomeans all mix MPN and copies in one column.
3. **Stratify `system_health` metrics by regime** so the San Diego labelling
   universe stops being invisible inside pooled numbers.
4. **Re-run the persistence A/B per regime** (already done once — see §9 — but
   re-run it whenever the serving path changes).
5. **Consider `assay × plume proximity` as the stratifier**, not `is_pcr` alone.
   The gradient in §5.3 says a binary flag is too coarse.
6. Backfill solar/wind over 2022–2025 if the photo-inactivation question matters.

## 9. Does this invalidate PR #28?

No — checked directly. The 2026-08-06 persistence override→floor A/B splits
cleanly by regime, and the floor wins in **both**:

| | PCR-labelled (n=1,242) | Culture-labelled (n=877) |
|---|---|---|
| realized rate | 0.8808 | 0.2805 |
| Brier — override | 0.1786 | 0.3101 |
| Brier — floor | **0.0778** | **0.1726** |
| AUROC — override | 0.500 | 0.500 |
| AUROC — floor | **0.9191** | **0.7700** |

The old override served a constant 0.6096 to every affected beach — **over**-warning
culture beaches (realized 0.28) and **under**-warning PCR beaches (realized 0.88)
simultaneously. One constant cannot serve two regimes, under any reading of the
labels.

## 10. Data-quality notes

- **3 Mendocino rows** are `Enterolert` with `Copies/100ml` units (values 10–20).
  Enterolert is a culture MPN method, so the units are a typo — but
  `is_pcr_measurement`'s units-OR misclassifies them as molecular and judges them
  against 1413. Harmless at those values; a 200-MPN row mislabelled the same way
  would read clean. The detector is unit-string-fragile.
- **One `ddPCR` row is dated 2002-09-13**, twenty years before the program
  existed.
- **The method string was renamed** `ddPCR` → `MCB-ddPCR SOP018-000` on
  2026-01-09. Both match the `"pcr"` substring so detection survived — by luck.
- **The culture reference standard is itself unstable.** On 4,155 same-station
  same-day culture split replicates the two replicates give the same >104 verdict
  only **86.6%** of the time; exceedance rate is 0.049 on the lower replicate and
  0.183 on the higher. `beachwatch.py` deliberately takes the worst. Asking ddPCR
  to agree with culture above ~87% asks more than culture agrees with itself.

## 11. Open questions for San Diego DEH

1. **Does a single ddPCR result >1413 trigger an advisory on its own**, or is
   there a confirmatory resample / duration / geometric-mean rule? Our flag rate
   is ~60%; the actual advisory-day rate is ~38%. That gap suggests something
   sits on top of the threshold.
2. Is SOP018-000 or the CDPH approval letter available on request?
3. How do ddPCR results interact with an already-open closure (e.g. the ongoing
   Tijuana River closures)?
4. Is 1413 under review in light of the 2026 Coronado result?

A draft email covering these is in the session record for
`docs/HANDOFF_persistence_floor.md`.

## 12. Caveats and reproduction

- Pairs are a median **2.27 h** apart (5 of 1,175 share a timestamp) — separate
  water grabs, not split samples. Not fixable; tightening to ≤1 h leaves 329
  pairs with 15 culture positives.
- Only **6.3%** of ddPCR beach-days have a same-day culture, and the three
  highest-volume ddPCR stations contribute 0/1/0 pairs. The paired corpus is not
  representative of the population a threshold would govern.
- Only 12 beaches have ≥20 culture-clean paired rows.
- Distance-to-Tijuana is confounded with everything else that varies north-to-south
  along the coast. This data cannot separate "plume" from "south county".
- Three defensible estimators for an alternative threshold span **21×** (OLS
  14,433 / RMA 42,702 / inverse-regression 300,030), which is itself the finding.
- The advisory layer cannot arbitrate: on non-plume days not already posted,
  culture predicts a new posting at AUC **0.998** and ddPCR at **0.248** — San
  Diego posts those beaches off the culture result, so the record is circular.

All figures above are reproducible from `data/curated/observations.parquet`,
`data/curated/beach_day.parquet`, `data/curated/advisories.parquet`, and
`data/experiments/persistence_override_ab_predictions.parquet`.
