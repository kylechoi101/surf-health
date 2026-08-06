# Handoff — positive-persistence override → floor (PR #28)

**Status: the §3 blocking decision was TAKEN — the calibration fix is folded into
#28 (`_drop_pin_era_rows`), along with the NaN-fallback fix and the doc
corrections. §3 and §4/§5 below are retained as the record of what was found and
why; they are no longer outstanding except where marked.** Written 2026-08-06.

---

## 1. Where things stand

| | |
|---|---|
| Branch | `claude/high-card-probabilities-fzs6l6` |
| PR | [#28](https://github.com/kylechoi101/surf-health/pull/28) — the serving change |
| PR | [#29](https://github.com/kylechoi101/surf-health/pull/29) — PR template, independent, mergeable |
| Tests | 550 pass, `ruff check` clean |
| Deployed? | **No.** The daily pipeline still runs the old override. |

**What shipped in `ed78fa3`:** the serve-time positive-persistence *override*
(`where(persistence >= 0.5, 1.0, p)`) is removed and replaced by a
post-calibration *floor* at `_LOW_THRESHOLD`. The floor also moved out of the
`if serving_calibration is not None:` branch, where it previously did not apply
at all when no calibrator could be fitted. Adds `persistence_floor_applied` to
`forecasts.parquet` and `_HISTORY_COLUMNS`.

---

## 2. The original bug (settled — do not re-derive)

On the 2026-08-05 forecast, 17 beaches across 6 counties served an identical
`p_exceed = 0.45` with lab readings from 107 to 6628. Two corrections cancelled
into a constant: the override discarded the model's answer and pinned to 1.0,
then the daily serving isotonic mapped its whole top step
(`x ∈ [0.617, 1.0]`) back down to `y = 0.45`.

`exceeds_stv_last_obs` was **already a model feature** (`features.py:412`, absent
from the exclusion set at `features.py:593-621`), so the override was replacing a
learned, context-sensitive estimate with a constant.

Full detail is in `CLAUDE.md` § "Positive-persistence: override → FLOOR".

---

## 3. THE BLOCKING DECISION

An Opus code review found, and I independently verified, that **the shipped code
is not the arm that was measured.**

The A/B refit the serving isotonic per arm. Production cannot: it reuses one
calibrator fitted on a trailing 120 days of `forecast_history.parquet`, and
`p_fit` = `p_exceed_precal`, which under the old code **was the pin (1.0)** on
exactly the affected rows. So genuine model probabilities get pushed through a
map fitted on pin artifacts.

Verified against the shipped `data/curated/`:

- live calibrator `max(y) = 0.45` → **`p_exceed ≤ 0.45` for every row**, so
  `_VERY_HIGH_THRESHOLD = 0.70` is unreachable. Confirmed: shipped
  `max(p_exceed) = 0.4500`, zero rows above 0.70.
- pushing arm-B probabilities through the live calibrator:

| | A/B (per-arm refit) | shipped path (live calibrator) |
|---|---|---|
| Moderate | 638 | **999** |
| High | 382 | 1,120 |
| Very High | 1,099 | **0** |
| mean p | — | 0.3442 |

Those rows have an **actual exceedance rate of 0.6324**. The old override served
all 2,119 at 0.45 → High. Merging as-is sends **47% of them to Moderate** —
a downgrade on the highest-risk beaches, in the unsafe direction, until the
120-day calibration window rolls over.

### The candidate fix, measured

Exclude pin artifacts (`p_fit == 1.0`) from `fit_serving_calibration`
(`served_metrics.py:326-367`). Justified, not a hack: the 13,331 non-pinned rows
were never overridden, so they are genuine model probabilities — exactly what
post-change rows look like. The 482 pinned rows are the synthetic ones.

```
                    Brier on affected rows   Very High   mean p
current (pin-era)          0.2541                 0       0.344
excluding pins             0.1778               295       0.444
                                                   actual rate 0.632
```

**RESOLVED — option (a).** Folded into #28 as `_drop_pin_era_rows`, keyed on
"legacy row AND precal == 1.0" so it is self-limiting. Verified on the real
history: 482 rows excluded, `max(y)` 0.45 → 1.0, fit Brier 0.0684 → 0.0617 vs a
flat-base-rate baseline of 0.0673. Expect ~295/2119 rows in Very High on the
offline replay — a band empty since July, so watch the first run.

---

## 4. Corrections owed to my own claims

**All three are now corrected** in `CLAUDE.md` and the PR body. Kept here so a
reader who saw the earlier text knows it was wrong rather than trusting it:

1. **"This is also why Very High never fired" is an overclaim.** Very High is
   unreachable through the live map regardless of the pin. The 0 → 1,114
   restoration is a property of the per-arm refit only.
2. **The A/B headline numbers overstate the production effect** for the same
   reason. They are the ceiling, not the first-run result.
3. **"`p_exceed_precal` is now genuinely the model's own probability" is false on
   NaN rows** — see §5 M1.

---

## 5. Review findings

- **M1 — NaN fallback. FIXED.** It used to return `1.0` for
  persistence-positive rows, and `probabilities_precal` is snapshotted *after*
  it. So a failed prediction serves the loudest forecast in the product AND
  re-seeds pin contamination into the next day's calibrator, permanently at a low
  rate. Both branches now use `_LOW_THRESHOLD`; the floor still lifts the row off
  Low. Covered by
  `test_export_nan_probability_on_persistence_positive_row_does_not_serve_one`.
- **M2 — PARTIALLY ADDRESSED, still the biggest gap.**
  `_run_export_single_beach` never writes `forecast_history.parquet`, so
  `fit_serving_calibration` returns None in every test. The shipped bug was
  `pin × isotonic → plateau`; the isotonic half is untested end to end. Also
  uncovered: advisory floor + persistence floor on the same row, and the two-tier
  router (never runs in tests — the gate needs `winner == "xgb_undersample_ensemble"`).
  `test_served_metrics.py` now covers the calibrator fit itself
  (`test_fit_excludes_pin_era_rows_so_the_map_is_not_capped`), but nothing still
  exercises model → isotonic → floor → advisory floor → band as one chain through
  `_export_forecasts`. **Worth doing next.**
- **M4 — FIXED.** `test_export_persistence_floor_applies_without_serving_calibration`
  passed on the old code too (the pin satisfied both assertions), so it was not a
  regression test. Replaced with the M1 NaN-branch test above.
- **L2/L3/L4 — FIXED.** The backwards header, the `test_exceedance.py` note, and
  the 27-line orphan are corrected; the orphan now points at CLAUDE.md instead of
  restating numbers, per this repo's own rule that pinned figures drift.
- **L5** — `persistence_floor_applied` does not actually "mirror
  `advisory_floor_applied`": the latter is plumbed through the API schema and web
  bake; the new column stops at the parquet.

## 6. Verified correct — do not re-litigate

Index alignment of `persistence_floor_applied_flags[i]` (`build_inference_features`
resets both indices, so `idx == i`); the guard model
`hist_gbm_positive_persistence_guard` is genuinely untouched and the new floor is
a no-op on it; interval containment holds (`0` rows with `lower > p_exceed`);
backward compatibility of the new column across sqlite/parquet/API readers; and
no gate trips (mean `p_exceed` ~0.094 → ~0.08, well inside the 0.25×–4× band).

---

## 7. Reproducing the evidence

```bash
cd backend
python3.12 -m venv .venv312          # project requires >=3.12,<3.13
.venv312/bin/pip install -e ".[training]" -c constraints.txt
.venv312/bin/python -m pytest -q     # expect 548 passed
.venv312/bin/python scripts/compare_persistence_override_ab.py   # ~25 min
```

Committed outputs (a rerun costs a full retrain):

- `backend/scripts/compare_persistence_override_ab.py` — the A/B
- `data/experiments/persistence_override_ab_predictions.parquet` — 11,973
  held-out rows with `label`, `p_model`, `persistence_positive`, and both arms'
  served probabilities. **Any additional cut is a recompute, not a retrain.**
- `data/experiments/persistence_override_ab_results.json`

### Traps that cost me time

- `import torch` is unconditional at `models.py:19`, so the training extra is
  required even though the neural track is dropped.
- The project rejects Python 3.11 (`requires-python = ">=3.12,<3.13"`).
- `_export_forecasts` reindexes serve features onto the **training** feature
  columns, so a column missing from the training frame is silently dropped at
  serve time. This is how `exceeds_stv_last_obs` would revert to the method-blind
  `value > 104` fallback. Both branches are now pinned by tests.
- The scratchpad is **ephemeral** — the container is reclaimed. Commit anything
  that matters.

---

## 8. Open threads beyond this PR

1. **`exceeds_stv` is not one label.** Culture is judged against 104 MPN/CFU,
   San Diego ddPCR against 1413 copies; on 1,175 paired same-day samples they
   agree only 50.6%. ddPCR is 15.3% of rows but 51.9% of positive labels.
   **1413 is correct — do not change it** (CDPH-derived against raw ddPCR copies,
   EPA Region 9 approved). The fix is to carry `is_pcr` / `label_method` into
   `beach_day`, stratify `system_health` metrics by it, then **re-run this A/B
   per regime** — the affected rows here are overwhelmingly San Diego, so the win
   is unconfirmed outside that regime. Full detail in `CLAUDE.md`.
2. **Email to San Diego DEH** (draft exists in session history, not committed):
   does a single ddPCR result >1413 trigger an advisory, or is there a
   confirmatory-resample / duration rule? Our flag rate is ~60% against a ~38%
   advisory-day rate. Primary sources are 403 from this network policy.
3. **Culture labels are only 86.6% self-consistent.** On 4,155 same-station
   same-day split replicates, the two replicates disagree on the >104 verdict
   13.4% of the time; exceedance rate is 0.049 on the lower replicate and 0.183
   on the higher. `beachwatch.py:577-587` deliberately takes the worst sample, so
   the base rate this project reports sits on the pessimistic branch of a 3.7×
   range. Deliberate, but undocumented outside this file.
