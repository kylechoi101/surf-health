---
task: web-research-scoreboard
repo: /Users/kylechoi/shorelife-web-bake
worker: claude
created: 2026-10-02
status: done
---

## Goal

UPDATE_PLAN step 3.1 (web part) on the shorelife-web research page
(`app/(desktop)/research/page.tsx`), plus making the page describe the model that actually
serves. The repo is a git worktree of shorelife-web on branch `feat/research-scoreboard`
(cut from `origin/main`); `node_modules` is installed. Do not touch the other shorelife-web
checkout (`/Users/kylechoi/shorelife-web`) — it has someone's uncommitted work.

## Facts (backend, merged 2026-10-02)

- The served logistic is now **v2** (`model_version` `logit-lookup-offset-v2`):
  logit(p) = logit(lookup) + b0 + b1·R + b2·R·F + b3·W + b4·S + b5·D + b6·R·D, where D = 1 when
  the beach's most recent lab result (before the forecast day) was measured by ddPCR (San Diego's
  DNA method, judged at 1413 copies) and 0 for culture methods. `system_health.json
  ["serving_method"]["logit"]["coefficients"]` carries `ddpcr` and `R_ddpcr` (alongside
  intercept, R, RF, W, S); `features` lists all six. Adopted under `backend/app/ml/PROMOTION.md`
  on the 2026-10-02 comparison.
- `serving_method.live.forward_1_3d.head_to_head` now has, besides `served`, `p_exceed_lookup`,
  `p_exceed_ml`: `p_exceed_persistence`; each score has `within_beach_auroc`; each challenger
  entry has `ci` = `{within_beach_auroc: [lo, hi], auroc: [lo, hi], brier: [lo, hi]}` — the
  beach-cluster bootstrap 95% CI of (challenger − served); `reportable` requires ≥ 28 served
  days, ≥ the pair/positive minimums. `live.versions` lists the served versions pooled.

## In scope

1. `lib/api.ts` types: add `within_beach_auroc`, `ci`, `p_exceed_persistence`, `versions`, and
   the two new coefficients (all optional).
2. "Today's fit" block: the formula text and coefficient tiles show the six-term v2 model when
   `features` contains `ddpcr` (b5 · D, b6 · R·D, with a one-line plain explanation of D), and the
   current four-term text otherwise — so the page is right before and after the first v2 run.
3. A "Live scoreboard" table under the tiles: rows served / lookup / persistence / ML challenger,
   columns within-beach AUROC (first — it is the deciding metric), AUROC, AUCPR, Brier, and for
   each challenger the CI of its within-beach AUROC and Brier delta vs served; a status line with
   `n_pairs`, served days, and "reportable from 28 served days" when not reportable (show the
   numbers greyed, not hidden). One sentence explains within-beach AUROC in plain words (can the
   rating tell a dirty day from a clean day at the same beach; 0.5 = no). Link the decision rule
   (`https://github.com/kylechoi101/surf-health/blob/main/backend/app/ml/PROMOTION.md`).
4. A test in `tests/` (node:test, like the others) for any pure helper you add (formatting a CI,
   choosing the formula variant).

## Out of scope

- Other pages; the deploy workflow; the baker; any backend change.
- Pushing, merging or deploying (the PM does it).

## Allowed files

- app/(desktop)/research/page.tsx
- lib/api.ts
- lib/research-scoreboard.ts (new, for pure helpers)
- tests/research-scoreboard.test.mjs (new)

## Allowed packages

- none

## Acceptance

```bash
cd /Users/kylechoi/shorelife-web-bake
npm test              # all pass (201 before)
npx tsc --noEmit      # clean
npm run lint          # clean
```

## Phases

### Phase 25
Deliverable: types + pure helpers (CI formatting, formula variant) with tests.

### Phase 50
Deliverable: "Today's fit" shows v2 when `features` has `ddpcr`, v1 otherwise.

### Phase 75
Deliverable: the live scoreboard table with CIs and the reportable status line.

### Phase 100
Deliverable: all Acceptance commands pass, outputs pasted.

## Corrections

(appended by the PM; newest last; each entry dated)

### 2026-10-02 22:55 — before phase 100 (PM)

1. The backend attaches `ci` to EVERY challenger entry in `head_to_head` (`p_exceed_lookup`,
   `p_exceed_ml`, `p_exceed_persistence`). Render the lookup's CI too; only the served row has none.
2. Yes — remove the live rows from the older "Forward outcomes" table so a number appears once;
   keep that table's backtest rows.
3. Then phase 100 as written.
