<!--
Keep it short. Delete every section that doesn't apply — a lint fix does not
need a Blast radius section. The checklists exist because each line traces to
something that actually broke this repo once; they are not ceremony.
-->

## What & why

<!-- One or two sentences. What changes, and what goes wrong today without it. -->

## Type

- [ ] Bug fix
- [ ] Feature
- [ ] Model / training change
- [ ] Data pipeline or label change
- [ ] Infra / CI / deps
- [ ] Docs only

---

## Evidence

<!--
REQUIRED for model, data, and label changes. Delete for docs/lint/deps.

Numbers must be reproducible and dated. Cite the live artifact
(data/curated/system_health.json) or the script that produced them — never a
figure copied from CLAUDE.md, which is explicitly a drifting snapshot.
-->

| metric | before | after |
| --- | --- | --- |
|  |  |  |

- Source of these numbers: <!-- system_health.json @ <commit>, or path to the script -->
- Which regime were they measured in?
  - [ ] **Sample-days** (a lab result exists) — the easy case, ~1 day in 7
  - [ ] **Served / between-sample days** — where ~95% of served rows actually live
  - [ ] Held-out county (leave-one-county-out) / held-out beach
- [ ] AUCPR is only compared **within** a population (it is base-rate dependent; the
      eval and serving base rates differ ~3×, so a cross-population AUCPR delta is
      mostly arithmetic). Cross-population comparisons use AUROC.
- [ ] Uncertainty stated where it matters (cluster-bootstrap CI, or n and base rate).

## Blast radius

<!-- Delete any line that is plainly N/A. Answering "no" is fine; leaving it
     unanswered is what has bitten this repo before. -->

- [ ] **Does this change `exceeds_stv` or a threshold?** If yes: historical rows do
      **not** get relabelled on a normal run — `cli.py`'s incremental branch only
      re-normalises the last 7 days, so you get mixed-vintage labels that pass every
      gate silently. State the rebuild plan (`--start-date`, or delete
      `observations.parquet`).
- [ ] **Method-aware?** Enterococcus is judged against 104 MPN/CFU for culture and
      1413 copies for ddPCR. Anything that re-derives an exceedance or a magnitude
      from a raw `value` instead of reading `exceeds_stv` is method-blind and wrong
      for San Diego. (`beach_day.parquet` carries no method/units column at all.)
- [ ] **Retrain required?** Anything touching the label, the feature set, or the
      training window.
- [ ] **New/changed parquet column?** Note whether existing readers
      (`repositories/`, `serving_snapshot.py`, `validate_forecast.py`) tolerate it.
- [ ] **Published JSON?** It must go through `app/core/json_safe.py`. A bare `NaN`
      is not valid JSON and froze every downstream publisher once (#14).

## Tests

- [ ] New tests **fail against the old behaviour** — a test that passes both ways
      documents nothing.
- [ ] Full suite green locally: `pytest` + `ruff check` <!-- paste the count -->

## Gates & rollout

- [ ] Promotion / release / anomaly gates: unchanged, or the change is justified above.
- [ ] Expected effect on the forecast-anomaly gate (`validate_forecast.py`): the
      mean `p_exceed` shift must stay within 0.25×–4.0× of the previous run.
- [ ] Serving impact — bands moving, or the served probability distribution shifting.
- [ ] Anything to watch on the first daily run after merge.

## Docs

- [ ] `CLAUDE.md` updated if this changes pipeline behaviour, metrics, or a
      documented invariant — including correcting anything it now says that is false.

---

<!--
Before merging: CI must be observed GREEN, not assumed. #11 was reverted for
merging on an unconfirmed pass. And a green data commit is not a deploy — the API
serves a snapshot baked into the Render image, so `verify_deploy.py` is what
proves users actually got it.
-->
