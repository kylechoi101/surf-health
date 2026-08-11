# Action-value normalization of the bacteria-history features

**Status:** shipped on `fix/action-value-normalized-features`.
**Measured effect on model skill: indistinguishable from zero.** This is a
data-coherence fix, published because the defect is real and the correction is
provably safe — not because it made the model better. See
[The effect size](#the-effect-size) before citing anything from this document.

---

## The defect

`beach_day.enterococcus_value` is one numeric column holding two incompatible
units:

| assay | reports | action value | share of the 1095d window |
|---|---|---|---|
| culture (Enterolert, MF, EPA 1600, MTF, SM 9230…) | MPN or CFU / 100 mL | **104** | 84.5% |
| San Diego ddPCR (`ddPCR`, `MCB-ddPCR SOP018-000`) | copies / 100 mL | **1413** | 15.5% |

**Both action values are correct and regulatory, and neither is changed by this
work.** 1413 is a CDPH-developed value fitted against raw ddPCR copies (Crain et
al. 2021), approved by EPA Region 9 on 2020-10-06 and authorized under H&SC
§115880(d). The defect is not the thresholds; it is that fourteen model features
carried the *magnitude* of a column whose unit varies row to row:

```
enterococcus_value_lag_{1,2,3,7,14,21,28}
enterococcus_value_last_obs
enterococcus_geomean_30d_lagged
enterococcus_geomean_42d_lagged
geomean_30d_exceeds_35_lagged
geomean_30d_exceeds_104_lagged
geomean_42d_exceeds_35_lagged
days_since_enterococcus_value_obs        <- the one exception, see below
```

### Why an assay flag cannot fix it

This is the crux, and it was verified rather than assumed.

**A flag describes the CURRENT row's assay. A lag holds a PREVIOUS row's
value.** Measured on the shipped `beach_day.parquet` (1095-day window, supported
stations, 88,766 rows across 649 beaches):

- **46 beaches carry both assays** — 9,946 rows. Their median reading is
  **1,893.5 copies** by ddPCR against **8.0 MPN** by culture: a ~237x step
  change in the same column, on the same beach, meaning roughly the same water.
- **2,114 rows (2.38% of the window, 21.3% of those beaches' rows)** have a
  previous sample from the *other* assay. On those rows `*_lag_1` /
  `*_last_obs` is a number from the other scale. (The A/B below scores 2,136 —
  the same rows counted on the labeled, scored subset.)
- **2,069 rows (2.33%)** have at least one of the seven exact lags landing on a
  row of the other assay.
- **The geomeans are worse: 4,624 rows (5.21%)** have a lagged 30-day window that
  averages MPN and copies together *before* the model sees the number. A per-row
  flag cannot annotate a value that has already been averaged.

And there is **no lagged assay indicator in the feature set** to disambiguate
them. Enumerated directly against the feature frame `origin/main` builds from
the shipped `beach_day`: of **214** model feature columns, the number matching
`pcr|method|units|assay|copies` is **zero**. The model had no input that could
tell it which scale a lag was on.

## The fix

`build_beach_day_frame` now emits **`enterococcus_action_ratio`** = the reading
divided by the action value *that reading* is judged against, and every
value-derived feature is built from it.

```
culture 52 MPN     -> 52 / 104   = 0.5
ddPCR   706.5 cop. -> 706.5 /1413 = 0.5     # same water quality, same number
```

`1.0` means "at the action value" for either assay, so a lag crossing an assay
boundary is continuous. The per-row action value comes from the existing
`app.data.pipeline.exceedance.is_pcr_measurement` predicate — the same one
`compute_exceeds_stv` uses — lifted into a shared `action_value_for` so the two
cannot drift.

### The invariant

```
enterococcus_action_ratio > 1.0   ==   exceeds_stv
```

for both assays, by construction. Verified on all 492,713 valued rows of the
shipped `beach_day` rebuilt from `observations.parquet` with this code:
**0 violations**.

### Decisions and their justifications

**1. The raw column is kept, unchanged, under its own name.**
`enterococcus_value` still holds the lab's own number. A census of the branch
(`git grep enterococcus_value`) finds its readers are: the feature builder, the
two training loaders, and the local-dev fixture path. **No reader in
`app/api`, `app/repositories`, `app/schemas`, `web/` or `mobile/`** — the API
surfaces sample values from `observations.parquet`, which this PR does not
touch. It was already excluded from the model feature set as a leaked target.
So keeping it costs one float column and guarantees nothing changes meaning
under a reader.

**2. Renamed what changed scale; kept what did not.**

| column | disposition | why |
|---|---|---|
| `enterococcus_action_ratio_lag_{1,2,3,7,14,21,28}` | **renamed** | the number is now a ratio; a name saying "value" would lie |
| `enterococcus_action_ratio_last_obs` | **renamed** | same |
| `enterococcus_action_ratio_geomean_{30,42}d_lagged` | **renamed** | same |
| `geomean_{30,42}d_exceeds_{35,104}_lagged` | **kept** | 35 and 104 name the regulatory trigger, which is unchanged; only the arithmetic testing it is now assay-correct |
| `samples_in_geomean_30d_lagged` | **kept** | a count |
| `days_since_enterococcus_value_obs` | **kept** | recency uses the column's *null pattern*, never its magnitude. The ratio is non-null in exactly the rows the raw value is, so the series is bit-identical. Renaming would churn `stale_evaluation.RECENCY_COLUMN` (the serving router's staleness constant), `spatial_diagnostics` and the bacteria-history regexes for zero information gain. |
| `log_enterococcus` | **kept raw** | see below |

**3. `log_enterococcus` deliberately stays on the raw scale.** It is not a model
feature (`_model_feature_columns` already drops it); it is the density
**regression target**, and the regressor's output is published to users as
`ForecastRecord.predicted_log_enterococcus`, with a serve-time fallback in
`serving_repository.py` that computes `log10(raw value)` directly. Moving it to
the ratio scale would silently change what a published number means and
desynchronise it from that fallback. Pinned by
`test_log_enterococcus_stays_on_the_raw_scale`. **It remains a genuinely
mixed-unit regression target** — see [Known remaining gaps](#known-remaining-gaps).

**4. The geomean triggers become ratios.** `104 -> 1.0` and `35 -> 35/104 ≈
0.3365`.

- On a **culture** beach this is the identical comparison (divide both sides by
  104), so the flags are bit-identical. Measured over the window: every culture
  row whose flag moved (560 / 419 / 563 for the three flags) is on a
  **mixed-assay** beach, and **zero** moved on a pure-culture beach or from the
  sub-detection floor change. That last clause holds only because the floor is
  per-assay — over full history a flat floor breaks it; see item 5.
- On a **ddPCR** beach the old rule compared a raw *copy* geomean against 35,
  which nearly every window clears. It was not a trigger, it was a San Diego
  indicator:

  | flag | ddPCR rows firing, before | after |
  |---|---|---|
  | `geomean_30d_exceeds_35_lagged` | **96.79%** | 77.26% |
  | `geomean_30d_exceeds_104_lagged` | **92.89%** | 59.24% |
  | `geomean_42d_exceeds_35_lagged` | **97.46%** | 77.75% |

  (culture rows, for contrast: 18.49% / 6.73% / 17.96% before, 17.74% / 6.17% /
  17.21% after.)

  📐 **Denominator.** Every count and rate in this section is over the **88,766
  evaluated rows** of the 1095-day window — the population the A/B scores. An
  earlier revision quoted the same quantities over the 94,425-row *build* frame,
  which additionally contains the 60-day rolling-window warm-up (`96.2 / 92.4 /
  96.9 -> 76.9 / 59.0 / 77.4`, and `588 / 442 / 591` moved culture rows). Those
  figures were arithmetically right on that denominator, but the warm-up rows are
  never scored and their geomeans are largely undefined, which deflated every
  rate by roughly half a point. Both were reproduced exactly; only the
  denominator changed.

  ⚠️ **There is no published ddPCR geomean action value.** §115880's 30-day
  geomean of 35 is a culture standard. `0.3365 x 1413 ≈ 476 copies` is a
  *proportional analogue*, not a regulatory trigger, and is documented as such
  in the code. It is defensible as the honest approximation; it is not a
  regulator's number.

**5. Sub-detection floor moves into ratio space — per assay.** The old convention
clipped the raw value at 1: "a reading of one reported unit logs as zero". Its
faithful ratio-space form is **one reported unit divided by that row's own action
value** — `CULTURE_RATIO_SUBDETECTION_FLOOR = 1/104` for a culture result,
`PCR_RATIO_SUBDETECTION_FLOOR = 1/1413` for a ddPCR one. The per-row divisor is
recovered inside `features.py` as `raw / ratio` and snapped to the two known
action values (`implied_action_values`), so `beach_day` still carries no assay
column.

**What the floor actually does.** It is not inert, and an earlier revision of this
document was wrong to say "no real reading is ever clipped by it":

| reading | rows, all of history (`observations`, and `beach_day`) | raw `clip(lower=1)` | flat `1/1413` | per-assay (shipped) |
|---|---:|---|---|---|
| `value < 0` (−999 / −1000 sentinels that survived the guards) | 280 (278) | clipped | clipped | clipped |
| `value == 0` (non-detect) | 1,602 (1,397) | clipped | clipped | clipped |
| `0 < value < 1` (every one of them is exactly `0.5`) | 31 (27) | clipped | **30 of 31 NOT clipped** | clipped |

Negative values *are* real rows and they *are* clipped; the floor is what keeps
`log10` finite on them. And a flat `1/1413` floor sits *below* one culture unit
(`104/1413 = 0.0736` raw), so it silently stopped clipping the 30 culture rows
reading `0.5 MPN` that the old rule did clip — only the single `0.5 copies` ddPCR
row still floored. What is true — of the per-assay floor — is that no reading of
**one reported unit or more** is ever touched, which is the property the geomeans
need.

**Why a single constant is wrong.** The flat `1/1413` this PR originally shipped
is one *molecular* copy; applied to a culture row it clips 13.59× lower than
`clip(lower=1)` did. That breaks the property the whole change rests on — on a
beach that only ever used culture there is no assay mixing, so the move to the
ratio scale must be a **pure monotone rescale** by 1/104, hence provably
invariant for tree models. Measured on pure-culture beaches only:

| pure-culture beaches only | flat `1/1413` | per-assay |
|---|---|---|
| trigger flags moved, **full history** (411,214 rows / 752 beaches) | **29 / 6 / 52** (87 total) | **0 / 0 / 0** |
| 30-day geomeans off the exact 1/104 rescale, full history | **3,519** (max rel. dev. **0.926**) | **0** (max rel. dev. **6.7e-15**) |
| same, **1095-day window** (71,281 rows of the A/B population) | 0 flags; **115** 30-day + **144** 42-day values | 0; 0 |

So the "measured impact on the geomean flags: zero rows" this document previously
claimed was true **in-window** and false over full history, where the flat floor
moves 87 flags. The null result's justification — "monotone rescale ⇒ trees
invariant ⇒ null expected" — only holds under the per-assay floor, and it has to
hold on exactly the population where no assay mixing is possible. Pinned by
`test_culture_only_ratio_geomeans_are_an_exact_rescale_of_the_raw_ones`, which
reimplements the raw convention independently and fails under a flat floor.

**Does this move the A/B?** Not materially, but not by zero either, and the A/B
was **not** re-run. Inside the scored population the floor change alters 125
30-day and 166 42-day geomean values (of ~86k defined) and exactly **one**
`geomean_42d_exceeds_35_lagged` bit, on a mixed-assay beach. Those are model
inputs, so every figure in the tables below could shift in the far decimals; ~291
changed cells out of 88,766 × 214 cannot change a conclusion, and the direction of
the correction is to make the culture stratum *more* inert, which is what the
reported null already says.

⚠️ **One documented gap.** `raw == 0` makes the quotient 0/0, so those rows fall
back to the culture action value. Over all of history exactly **4** ddPCR
observations report 0, so at most 4 rows get a 1/104 floor where 1/1413 was
meant. Everything else — including every negative sentinel and every
`0 < value < 1` reading — resolves its own assay exactly.

**6. A build-time tripwire.** `assert_no_raw_value_features` runs inside
`_model_feature_columns` and raises `RawEnterococcusFeatureError` if any model
feature name mentions the raw column. The allowlist has exactly one entry
(`days_since_enterococcus_value_obs`, justified above). The next feature added
on the wrong column fails loudly instead of silently — which is how the original
defect was introduced.

---

## Verification: the label does not move

`exceeds_stv` is computed from the **raw** value against the correct threshold
and is the training label. It must not move. Rebuilding the entire shipped
`beach_day` (492,731 rows) from `observations.parquet` with this code:

| check | result |
|---|---|
| rows in / out | 492,731 / 492,731, no row added or dropped |
| **`exceeds_stv` flips** | **0** |
| `enterococcus_value` changed | **0** |
| `ratio > 1.0 == exceeds_stv` violations | **0** of 492,713 valued rows |
| implied action values | 104 on 472,505 rows, 1413 on 18,811 |

Pinned by `tests/test_action_value_normalization.py`, including the two rows
that fix the thresholds in place: 1000 copies is **clean** (below 1413) while
200 MPN **exceeds**.

---

## The A/B

Same rows, same labels, same covariates, same model, same folds, same seed. The
only difference is which column the fourteen bacteria-history features derive
from — verified at runtime: the two feature frames are **214 columns each and
differ in exactly the 10 renamed columns**.

| | |
|---|---|
| population | shipped `beach_day.parquet`, supported stations, 1095-day window (2023-08-09 → 2026-08-08) |
| rows scored | 88,766 across 649 beaches, 15,638 positives (base rate 0.176) |
| folds | 5-fold `GroupKFold` on `beach_id` — **held-out beaches**, ~130 unseen beaches per fold |
| model | `XGBUndersampleEnsemble` (the production winner), defaults, `random_state=20260810` |
| calibration | isotonic, fitted per fold on a 20% held-out slice of the *training* beaches, identical split across arms |
| arm A | `origin/main`'s `features.py`, loaded as an independent module |
| arm B | this branch's `features.py` |

**Guards on the harness itself.** Arm A is `origin/main`'s `features.py` loaded
as an independent module. Its `_model_feature_columns` knows nothing about
`enterococcus_action_ratio`, so without an explicit exclusion it would have
received *today's reading* as a feature and "won" on a leak; the harness drops
`{enterococcus_value, enterococcus_action_ratio, log_enterococcus}` from both
arms. It also drops the `is_pcr` / `assay_switch` analysis columns — handing the
model an assay flag is precisely the intervention this document argues cannot
work, so it must not enter through the test rig.

### Discrimination and the Searcy operating point

Sensitivity **and PPV** at specificity 0.87 — AUROC alone hides precision.

| stratum | n | positives | base rate | arm | within-beach AUROC | sens @ spec .87 | **PPV @ spec .87** |
|---|---:|---:|---:|---|---:|---:|---:|
| **ALL** | 88,766 | 15,638 | 0.176 | A raw | 0.7746 | 0.8186 | 0.5811 |
| | | | | **B ratio** | **0.7741** | **0.8229** | **0.5779** |
| **culture** | 75,029 | 7,517 | 0.100 | A raw | 0.7694 | 0.7286 | 0.3843 |
| | | | | **B ratio** | **0.7672** | **0.7214** | **0.3916** |
| **ddPCR** | 13,737 | 8,121 | 0.591 | A raw | 0.8109 | 0.8485 | 0.9080 |
| | | | | **B ratio** | **0.8182** | **0.8503** | **0.9092** |
| **assay-switch rows** | 2,136 | 564 | 0.264 | A raw | 0.6526 | 0.6702 | 0.6495 |
| | | | | **B ratio** | **0.6420** | **0.6525** | **0.6445** |

The "assay-switch rows" stratum is exactly the population this fix targets: rows
whose previous sample used the other assay. n = 2,136, i.e. the 2.38% scope.

### Brier, against two reference constants

`flat global` is the population-wide exceedance rate quoted for every row;
`flat stratum` is what a forecaster who knew only the stratum would quote —
the harder reference, and the one that matters for the ddPCR stratum whose base
rate is 0.591 against 0.176 overall.

| stratum | arm | Brier | flat global | flat stratum |
|---|---|---:|---:|---:|
| **ALL** | A raw | 0.06751 | 0.14514 | 0.14514 |
| | **B ratio** | **0.06699** | | |
| **culture** | A raw | 0.06131 | 0.09592 | 0.09015 |
| | **B ratio** | **0.06073** | | |
| **ddPCR** | A raw | 0.10138 | 0.41392 | 0.24169 |
| | **B ratio** | **0.10116** | | |
| **assay-switch rows** | A raw | 0.13773 | 0.20205 | 0.19433 |
| | **B ratio** | **0.13762** | | |

Both arms beat both constants in every stratum, and they beat each other by
nothing worth naming.

### Paired cluster bootstrap, unit = beach, 2,000 draws

Positive means arm B (normalized) is better.

| stratum | beaches | Brier(A) − Brier(B) | 95% CI | within-beach AUROC(B) − (A) | 95% CI |
|---|---:|---:|---|---:|---|
| ALL | 649 | +0.00053 | [+0.00007, +0.00106] | −0.00053 | [−0.00309, +0.00194] |
| culture | 613 | +0.00058 | [+0.00013, +0.00118] | −0.00215 | [−0.00490, +0.00070] |
| ddPCR | 82 | +0.00028 | [−0.00135, +0.00236] | **+0.00724** | **[+0.00116, +0.01345]** |
| assay-switch rows | 57 | +0.00018 | [−0.00185, +0.00248] | −0.00999 | [−0.02735, +0.00536] |

---

## The two specific checks

### 1. Does the latitude residual collapse? — **No.**

The standing hypothesis was that the strong `|Spearman|` of the short lags
against latitude is the unit mixing surfacing as apparent geography. Re-tested
properly:

| feature | arm A (raw) | arm B (ratio) | n rows | |ρ| removed |
|---|---:|---:|---:|---:|
| `*_lag_1` | −0.6938 | −0.5599 | 18,268 | 19% |
| `*_lag_2` | −0.7407 | −0.5881 | 15,117 | 21% |
| `*_lag_3` | −0.7737 | −0.6509 | 12,799 | 16% |
| `*_lag_7` | −0.2348 | −0.1613 | 59,059 | 31% |

Normalization removes roughly a fifth of the association and **leaves the
majority intact**. This independently reproduces an earlier probe (0.7532 /
0.7802 -> 0.6056 / 0.6622) on a differently-built pipeline, so the finding is
not an artefact of either implementation.

**And most of what remains is not geography either — it is sampling cadence.**
A row only *has* a `lag_2` if the same beach was sampled two days earlier, and
near-daily sampling in California is overwhelmingly San Diego's ddPCR program:

| feature | rows that have it | ddPCR share | San Diego share | median latitude |
|---|---:|---:|---:|---:|
| window baseline | 88,766 (100%) | 15.5% | 24.8% | — |
| `*_lag_1` | 18,242 (20.6%) | 45.1% | 48.5% | 33.62 |
| `*_lag_2` | 15,071 (17.0%) | 48.9% | **50.9%** | 32.98 |
| `*_lag_3` | 12,758 (14.4%) | 53.9% | **55.2%** | 32.68 |
| `*_lag_7` | 58,501 (65.9%) | 18.0% | 26.6% | 33.72 |

Rows carrying a `lag_2` are **50.9% San Diego** against a **24.8%** window
baseline; `lag_3` rows are **55.2%** San Diego. `lag_7` — available on 65.9% of
rows and only 26.6% San Diego — shows a far weaker association (|ρ| 0.235 ->
0.161) on both scales. So the short-lag/latitude correlation is largely a
**selection effect of who gets sampled daily**, on a population where San Diego
genuinely is dirtier (base rate 0.406 vs 0.102 elsewhere).

**Conclusion: the unit mixing was one contributor, not the explanation.** The
"latitude proxies for a real San-Diego-is-dirtier signal" reading survives, and
a third contributor — cadence-driven selection into the lag-bearing population —
is identified here and is not addressed by this PR.

### 2. Effect size — is the improvement suspicious?

It is not, because there is essentially no improvement to be suspicious of. See
below.

---

## The effect size

**Null.** Every headline comparison is inside noise, and the two intervals that
do exclude zero are too small to act on.

- **Overall within-beach AUROC: −0.0005, 95% CI [−0.0031, +0.0019].**
  Indistinguishable from zero. This is the metric that matters (global AUCPR is
  dominated by between-beach variance and is blind to daily skill), and it did
  not move.
- **Overall Brier: +0.00053, 95% CI [+0.00007, +0.00106].** The interval
  excludes zero, so the improvement is statistically detectable — and it is
  **0.8% of a Brier of 0.067**. Detectable is not meaningful. Note also that
  this is one of eight intervals reported; no multiplicity correction is
  applied, and a nominal-95% interval that barely clears zero should be read
  accordingly.
- **On the 2,136 rows the fix actually targets, the point estimate goes the
  wrong way**: within-beach AUROC −0.0100, 95% CI [−0.0274, +0.0054];
  sensitivity 0.670 → 0.653. There is **no evidence of benefit on the affected
  rows**, and with only 57 beaches the interval is ±0.016 wide — about thirty
  times the overall effect — so this stratum could not have detected a small
  real gain either. It is uninformative, not contradictory.
- **The one result that goes the predicted direction with a CI excluding zero
  is ddPCR within-beach AUROC: +0.0072, 95% CI [+0.0012, +0.0135].** It is
  mechanistically plausible — ddPCR beaches are where the scale was wrong and
  where the geomean triggers went from 96% constant to 77% informative — but
  +0.007 on 82 beaches is small, and it is not a result to build a claim on.

**Verdict: this change does not measurably improve the model.** It is published
as a correctness fix, not a performance one, and nothing downstream should cite
it as a skill improvement.

### Why a large effect was never plausible, and why that is the point

Three independent reasons the ceiling on this change is low:

1. **It touches 2.38% of rows directly.** The assay-crossing lag rows are 2,114
   of 88,766.
2. **On a pure-culture beach the transform is provably inert.** Dividing one
   feature by a constant is a strictly monotone rescale, and gradient-boosted
   trees are invariant to monotone rescaling of an individual feature; the
   geomean trigger thresholds rescale by the same constant, so those flags are
   bit-identical. Measured: **zero** flag changes on pure-culture beaches, over
   the window *and* over full history, and the geomeans match the raw-derived
   ones to 6.7e-15 relative. This is exactly the property the per-assay
   sub-detection floor exists to preserve — under a flat floor it fails (item 5),
   which is why the floor was fixed before this argument could be relied on. The
   only reachable effect is (a) mixed-assay beaches and (b) the *relative*
   scaling between culture and ddPCR rows, which a global model's shared split
   thresholds can see.
3. **The evaluation is held-out beaches**, so a fold's test beaches are
   frequently pure-culture, where by (2) the two arms are the same model.

**A large measured gain here would be evidence of a leak, not of skill.** The
honest result is a null, and it is published as one.

**What this change buys is not accuracy — it is definedness.** Before it, a
number in the model's input meant "MPN" on some rows and "copies" on others with
nothing distinguishing them, the geomean averaged the two, and one feature
family was a near-constant San Diego indicator wearing a regulatory name. Those
are defects whether or not fixing them moves a metric this quarter, and the
features are now correct for whatever model is trained on them next.

---

## Known remaining gaps

Deliberately **not** fixed here, to keep this branch reviewable on its own:

1. **`log_enterococcus` is still a mixed-unit regression target.** It is
   published as `predicted_log_enterococcus`, so a fix has to change a
   user-facing number's meaning and the serve-time fallback together. Separate
   PR.
2. **`CuratedRepository._derived_forecast` is method-blind.** The API's
   persistence fallback computes `ratio = latest_value / self.stv_threshold` and
   says *"above the marine threshold"* — using 104 for every row, including San
   Diego copy counts. Same defect class, serving layer rather than feature
   layer, out of scope here.
3. **`exceeds_stv` is not one label.** Culture rows are judged against 104,
   ddPCR against 1413, and on paired same-day samples the two rules agree only
   ~50% of the time. ddPCR is 15.5% of window rows but supplies **51.9% of all
   positive labels**. Normalizing the *features* does not make the *label*
   homogeneous, and leave-one-county-out with San Diego held out is still
   holding out a different labelling universe. Carrying `is_pcr` / `label_method`
   into `beach_day` and stratifying `system_health` metrics by it is the next
   step, and it is deliberately separate from this one — this PR's argument is
   precisely that an assay flag does *not* repair the features, so the two
   changes must be measurable apart.
4. **The ddPCR geomean analogue has no regulatory basis** (decision 4 above).

## Reproducing

From `backend/`:

```
.venv/bin/python scripts/ab_action_value_normalization.py
```

Roughly 25 minutes; needs `beach_day.parquet` and `observations.parquet` in
`data/curated/`. Writes `data/experiments/action_value_normalization/` —
`ab_results.json` (every table above) and `ab_predictions.parquet` (per-row
held-out predictions for both arms, with `is_pcr` and `assay_switch`), so any
further cut is a recompute rather than a retrain. Both are committed.

The scope, label-invariance and geomean-degeneracy figures are reproduced by
`tests/test_action_value_normalization.py` on synthetic frames and by the
rebuild-and-compare in the [verification section](#verification-the-label-does-not-move).
