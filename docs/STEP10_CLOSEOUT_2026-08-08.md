# Programme close-out — E1–E7 scored

Closes the 10-step rebuild defined in `REBUILD_STEPS.md`. Scored 2026-08-08
against artifacts on disk, not against intent.

**Verification state at close:** 733 backend tests pass, ruff clean, baseline
`data/baseline/2026-08-07/` **9/9 sha256 intact**, nothing committed or pushed,
CI untouched. All work is uncommitted on branch `step2-weather-backfill`.

---

## Scorecard

| | property | verdict | evidence |
|---|---|---|---|
| **E1** | Calibrated in the served regime | ❌ **NOT MET — calendar-gated** | Fit window is 86.3% pre-router / 6.9% unknowable / 6.9% router-era / **0.0% current config**. Cannot be fixed by filtering (leaves 0 pairs). Needs ~60 days of single-regime history, which Step 9's tenure floor starts accruing. |
| **E2** | Bands empirically separated | ⚠️ **PARTIAL** | Low/Moderate cut moved 0.20 → 0.10, derived from `p_exceed_precal` over 11,000+ rows. Moderate (0.110) and High (0.216) no longer overlap. **High/Very High (0.70) remains provisional** — 95% of `p ≥ 0.45` evidence predates the router and the pin removal. |
| **E3** | No metric pools two assay universes | ✅ **MET** | **402 assay-stratified keys** verified in the shipped `system_health.json`. AST guard test fails the build on a new pooled call site. |
| **E4** | Within-beach AUROC is the headline | 🟡 **CODE-COMPLETE, ARTIFACT-PENDING** | `headline_metrics` block implemented; **not yet in the shipped JSON** — it lands on the next real pipeline run. Verified absent on disk today. |
| **E5** | System can identify its own regimes | 🟡 **CODE-COMPLETE, ARTIFACT-PENDING** | `serving_config_fingerprint` implemented and proven to move on a constant change (`0ad71d…` → `02331…` → `6c28d645ca929f34`). **The column is not yet populated in `forecast_history.parquet`** — it lands forward-only on the next run. Historical rows will stay null; that is correct, not a gap to backfill. |
| **E6** | Mechanism features exist | ✅ **MET — and the answer was negative** | All 7 weather features **22.2% → 100%** on 2020+; `dist_to_chronic_source_km` at 100%. Measured on held-out beaches, the features are worth ~nothing (see below). The property was to *measure honestly*, and it was. |
| **E7** | Model card states irreducible limits | ✅ **MET** | `data/curated/model_card.md` rewritten with all three irreducible limits plus every negative finding, unsoftened. |

**Two met, one met-with-a-negative-result, one partial, two pending a pipeline
run, one calendar-gated.** E1 and E2's remainder were designed to be
calendar-gated; they are not failures of execution.

---

## The one action required to close E4 and E5

Run the pipeline once. Both properties are implemented and tested; neither has a
shipped artifact because Step 8 deliberately refused to hand-write run outputs —
fabricating a run artifact to satisfy a checklist would have inverted the point
of the programme. After one daily run:

- `system_health.headline_metrics` appears → E4 met.
- `forecast_history.serving_config_fingerprint` begins populating → E5 met, and
  the ~60-day clock for E1/E2 starts from that run's fingerprint.

**Do not bundle further serving-path changes after that run.** Step 9 measured
that each change opens a new regime and restarts the 60/120-day clock, so every
separate change costs another full 60 days before E1 becomes measurable. The band
reset in Step 10 was deliberately bundled for this reason.

---

## What the programme actually established

The plan's thesis — *don't rebuild the model; fix the label and measurement
layers* — held. But it held for different reasons than the plan gave, and three
of the plan's own hypotheses were falsified by its own method.

**Falsified:**

- The **marine features** are worth **+0.0015 [−0.0042, +0.0053]**, not the
  long-claimed +0.029, and are *negative* on culture rows.
- **Photo-inactivation** is null once season and rain are controlled
  (r = −0.030 [−0.070, +0.010], down from an apparent −0.378).
- The **plume feature** is `latitude` (Spearman 0.9968) and scores **0.479 —
  below chance** on statewide culture rows. The −0.916 discordance correlation
  that motivated Phase 2 is an assay-regime gradient, not transport physics.

**Confirmed and strengthened:**

- The **persistence floor** generalises, and *more* strongly outside San Diego
  (+0.1447 [+0.1181, +0.1760]) than inside it.
- **`is_pcr`** earns its place as a feature and is not a San Diego proxy — an
  explicit San Diego indicator fails to recover its contribution.

**The central finding, which nothing in the plan anticipated:**

Pooled AUCPR **0.8168** concealed **culture 0.3875 / ddPCR 0.9707**. The regime
covering ~85% of California beaches scores 0.39, and on *lift* the ranking
inverts (5.58× vs 1.50×). Separately, on **both** assay strata the served
probabilities **lose to a flat constant** on Brier (0.0970 vs a stratum-aware
0.0756) while the pooled figure wins — the "beats flat base rate" claim was
measured against a weaker single-constant baseline.

**Three live production bugs were found incidentally and fixed:**

1. The daily incremental dedupe keyed `(beach_id, sample_time)` while the
   additive merges key on method/units/value too, destroying **1,949 rows /
   218 exceedances** — always in the false-negative direction.
2. Weather aggregation truncated **8,767 of 8,776** beach-days in 2026-04..07
   (`shortwave_24h_sum` understated 83%), because each 7-day refetch slice was
   aggregated in isolation and `keep="last"` never repaired it.
3. `uv_index` was silently null from the ERA5 archive for three months — HTTP
   200, key present, every value null — and had been substituting a
   `shortwave/80` proxy under a UV name.

---

## Corrections to `CLAUDE.md` that this programme requires

`CLAUDE.md` should not be trusted on these points until updated:

- "+0.029 AUCPR, spatially confirmed" for marine features — **not reproducible**.
- The persistence-floor A/B's "overwhelmingly San Diego ddPCR" caveat —
  **understates the result**; it generalises better outside San Diego.
- Any pooled AUCPR/Brier figure quoted as "how good is the product" — **must be
  stratified by assay** or it is Simpson's-paradox-contaminated.
- The San Diego base-rate framing — San Diego's *culture* base rate (0.0974) is
  marginally **below** the rest of California (0.1007). It is a labelling
  difference, not a contamination difference.

---

## Not done, and deliberately so

- **Nothing is committed or pushed.** The whole programme is a working tree on
  one branch. Review before merge; the label frame changed.
- **Step 4 Stage B is held.** A republished state export adds ~240k pre-2011
  beach-days (+49%) with 342 fully-attributed flips, but drags in a roster change
  850 → 924 that perturbs `shore_normal_wind_ms` on 36,906 *existing* rows. The
  1095d training window barely moves (+0.08%). Recommended as its own step.
- **No UI change was made.** The band-labelling decision is implemented
  backend-side (`RISK_BAND_DESCRIPTIONS`, `RISK_BAND_RELATIVE_SUMMARY`,
  `BAND_SEMANTICS = "relative_risk_tier"`); web and mobile must render the
  relative framing separately.
- **The `uv_index` proxy before 2022-08-04 is permanent.** The air-quality
  archive does not reach further back. Any UV-clean analysis starts 2022-08-04,
  which is also clean of the San Diego PCR-labelling transition.
