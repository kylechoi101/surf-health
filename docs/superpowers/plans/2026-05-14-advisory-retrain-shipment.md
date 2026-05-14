# Advisory Retrain + Shipment Plan

**Drafted:** 2026-05-14
**Status:** Pending execution
**Owner:** Kyle

## Goal

Ship three coordinated improvements as one atomic deploy across all 3 repos:
1. **Data cleanup**: Ventura-style stale state-feed records demoted when a county scraper succeeds (cleaned 215 → 52 active).
2. **Alias expansion**: Capture the ~23 live county advisories the parser currently drops, via the static alias CSV (San Mateo + Orange — inland reservoirs deferred until roster expansion).
3. **Band rename**: `risk_band` for advisory-active beaches displays as `"Advisory"` (purple) instead of `"Very High"` (red), with explanation copy + advisory-source link in web + mobile.

Plus: retrain on the cleaned + expanded feature matrix, with all 11 models (including sequence: TCN/CNN/LSTM/Transformer/PINN) and full spatial backtests.

## Why now

- The 5h "rigorous" training already happened on PRE-cleanup data, with 2,275 inflated `advisory_active_prev_14d=True` rows in the 365-day training window. That artifact is stale.
- Cleanup reduces noise in the advisory feature; sequence models showed real promise in the prior run (LSTM 0.76 county-AUCPR vs hist_gbm 0.66) and should be re-tested on cleaner data.
- The band rename is independent UX work that's already implemented locally — bundling it ensures the data semantic ("Advisory") and the displayed label move together.

---

## Phase 0 — Pre-flight (5 min)

```bash
cd /Users/kylechoi/surf_health

# Confirm cleaned data is on disk + backups intact
ls -lh data/curated/*.bak-pre-{retrain,scrape,cleanup} 2>/dev/null | wc -l   # expect ≥11

backend/.venv/bin/python -c "
import pandas as pd
a = pd.read_parquet('data/curated/advisories.parquet')
print(f'active advisories: {(a.status==\"active\").sum()}')  # expect ~52
bd = pd.read_parquet('data/curated/beach_day.parquet')
print(f'beach_day rows w/ advisory_active_prev_14d: {bd.advisory_active_prev_14d.sum()}')  # expect 84226
"

# Pin baseline (current system_health is from the pre-cleanup 5h training)
cat data/curated/system_health.json | python3 -c "
import json, sys
h = json.load(sys.stdin)['model_registry']
print(f'BASELINE production AUCPR: {h[\"production_metrics\"][\"aucpr\"]:.4f}')
print(f'BASELINE production Brier: {h[\"production_metrics\"][\"brier\"]:.4f}')
print(f'BASELINE winner: {h[\"production_model\"]}')
print(f'BASELINE eligible: {h[\"public_release_eligible\"]}')
"
```

**Gate**: any failure → restore from backups, stop.

---

## Phase 1 — Expand alias CSV from live audit (~15 min)

The `audit` agent (run separately) appended entries to `_static_data/county_beach_name_to_station.csv`. Verify they work, then re-run the scraper so the new advisories land in `advisories.parquet`.

```bash
# Verify alias CSV grew
wc -l backend/app/data/pipeline/_static_data/county_beach_name_to_station.csv

# Re-run scrape with the new aliases (uses the cleanup logic from Phase 0 too)
cd backend
.venv/bin/python scripts/fetch_county_advisories.py --curated ../data/curated 2>&1 | tail -20

# Verify active count expanded (was 52, expect higher — closer to ~60-65)
.venv/bin/python -c "
import pandas as pd
a = pd.read_parquet('../data/curated/advisories.parquet')
act = a[a.status=='active']
print(f'active: {len(act)}')
print(act.groupby('county').size().sort_values(ascending=False).to_string())
"
```

**Skipped (deferred, not in this shipment):**
- East Bay 7 inland lakes (Lake Chabot, Shadow Cliffs, Del Valle, Lago Los Osos, Horseshoe/Niles, Rainbow Lake) — these are freshwater, not in the marine beach roster, would need feature engineering changes (no wave/marine wind covariates apply).
- Marin "Inkwells" — inland swim hole, same story.

**User action**: send the 8 county outreach emails from `/Users/kylechoi/shorelife-private-backup/outreach/county_advisory_inquiry_drafts/` to get documented feeds long-term.

---

## Phase 2 — Retrain with all models (~5h, AC required)

```bash
# Confirm AC power
pmset -g batt | head -2

# Full-rigor retrain: all 11 models incl. 5 sequence (TCN/CNN/LSTM/Transformer/PINN),
# all 14 cores via OpenMP/BLAS env, full spatial backtest.
cd /Users/kylechoi/surf_health/backend
OMP_NUM_THREADS=14 MKL_NUM_THREADS=14 OPENBLAS_NUM_THREADS=14 \
VECLIB_MAXIMUM_THREADS=14 NUMEXPR_NUM_THREADS=14 \
.venv/bin/python -m app.ml.training \
  --curated --forecast-date 2026-05-14 \
  --spatial-backtests --spatial-strategy requested \
  --spatial-beach-limit 500 --spatial-county-limit 30 \
  --training-window-days 365 --forecast-min-recency-days 45 \
  --model all > /tmp/retrain_final.log 2>&1 &
TRAIN_PID=$!

# Attach caffeinate so lid-close doesn't suspend the process.
caffeinate -i -s -w $TRAIN_PID > /tmp/caffeinate.log 2>&1 &
```

**ETA**: 4-5h. Sequence model spatial backtests dominate (~3-4h alone). Notification fires on completion.

**Why all models, including sequence:**
- Cleaner data means sequence models get less-noisy training signal.
- Prior run showed LSTM at 0.76 spatial county AUCPR vs hist_gbm's 0.66 — worth a real apples-to-apples comparison on cleaned data.
- They land in `research_models` (not promoted candidates) by default, so this is safe research signal without changing what serves users.

---

## Phase 3 — Verify (15 min)

```bash
cd /Users/kylechoi/surf_health

# 3a. Promotion gates
.venv/bin/python -c "
import json
h = json.load(open('data/curated/system_health.json'))['model_registry']
print(f'winner: {h[\"production_model\"]}')
print(f'deployment_stage: {h[\"deployment_stage\"]}')
print(f'public_release_eligible: {h[\"public_release_eligible\"]}')
print(f'promotion_blockers: {h[\"promotion_blockers\"]}')
print(f'production AUCPR: {h[\"production_metrics\"][\"aucpr\"]:.4f}')
print(f'production Brier: {h[\"production_metrics\"][\"brier\"]:.4f}')
"

# 3b. Compare against pre-cleanup baseline
.venv/bin/python -c "
import json
old = json.load(open('data/curated/system_health.json.bak-pre-retrain'))['model_registry']
new = json.load(open('data/curated/system_health.json'))['model_registry']
for m in ['aucpr','brier','log_loss','calibration_slope','precision_at_80_recall']:
    ov, nv = old['production_metrics'][m], new['production_metrics'][m]
    print(f'{m}: {ov:.4f} → {nv:.4f}  (Δ {nv-ov:+.4f})')
"

# 3c. Advisory audit (should improve — stale pool eliminated, acute pool grows)
.venv/bin/python -c "
import json
a = json.load(open('data/curated/advisory_audit.json'))
print(f'active_advisories: {a[\"active_advisories\"]}  (was 49 pre-cleanup)')
print(f'overall agreement: {a[\"agreement_rate\"]:.3f}  (was 0.204)')
for pool, m in a['pool_metrics'].items():
    print(f'  {pool}: {m[\"advised_beaches\"]} advised, {m[\"model_flagged\"]} flagged, agreement={m[\"agreement_rate\"]}')
"

# 3d. Sequence model spatial leaderboard (research signal, doesn't gate ship)
.venv/bin/python -c "
import json
sm = json.load(open('data/curated/system_health.json'))['model_registry']['spatial_metrics']
beach = {k.replace('spatial_beach_',''): v for k,v in sm.items() if k.startswith('spatial_beach_')}
county = {k.replace('spatial_county_',''): v for k,v in sm.items() if k.startswith('spatial_county_')}
print(f'{\"model\":42s} {\"beach AUCPR\":>11s} {\"county AUCPR\":>12s}')
for m in sorted(set(beach) | set(county)):
    b = beach.get(m,{}).get('aucpr'); c = county.get(m,{}).get('aucpr')
    if b is None and c is None: continue
    print(f'{m:42s} {b:>11.4f} {c:>12.4f}' if b and c else f'{m:42s} -')
"

# 3e. Rebuild serving snapshot + local smoke test
cd backend
.venv/bin/python -m app.data.pipeline.serving_snapshot --curated ../data/curated
.venv/bin/uvicorn --app-dir . app.main:app --host 127.0.0.1 --port 8767 &
UVICORN_PID=$!; sleep 3

# Confirm Advisory band on a fresh SD beach
curl -s 'http://127.0.0.1:8767/beaches/ca604254-san-diego-coronado-north-beach-eh-060/forecast?date=2026-05-14' \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'risk_band: {d[\"risk_band\"]!r}  (expect Advisory)')
print(f'model_risk_band: {d[\"model_risk_band\"]!r}  (expect Low or similar)')
print(f'advisory_floor_applied: {d[\"advisory_floor_applied\"]}')
"

# Parent band distribution
curl -s 'http://127.0.0.1:8767/parent-beaches' | python3 -c "
import json, sys
data = json.load(sys.stdin)
bands = {}
for p in data: bands[p.get('risk_band')] = bands.get(p.get('risk_band'),0)+1
print('parent band distribution:', bands)
"

# Health 200 + no 503
curl -s 'http://127.0.0.1:8767/system/health' -o /dev/null -w 'health: %{http_code}\n'
kill $UVICORN_PID
```

**Promotion gates** (must pass before commit):
- ✅ `public_release_eligible == True` AND `promotion_blockers == []`
- ✅ `ΔAUCPR ≥ -0.005` (small regression OK; large regression → rollback)
- ✅ Acute pool agreement ≥ 50% when ≥3 acute advisories (the audit gate)
- ✅ `/system/health` returns 200
- ✅ Advisory beach returns `risk_band: "Advisory"` with `model_risk_band` populated

**If gates fail**: restore from `*.bak-pre-{retrain,cleanup}` backups, investigate, do not commit.

---

## Phase 4 — Commits (3 repos, atomic-deploy order)

Commit & push in this order so consumers (web/mobile) are ready before the backend flips:

### Commit 1 — shorelife-mobile

```bash
cd /Users/kylechoi/shorelife-mobile
git status --short  # review

git add lib/api.ts lib/utils.ts lib/theme.ts lib/forecastPresentation.ts \
        components/RiskSystem.tsx \
        app/\(tabs\)/map.tsx \
        app/beach/\[id\]/detail.tsx

git commit -m "$(cat <<'EOF'
feat(risk-band): add 'Advisory' band for official county postings

Renames the displayed risk_band from 'Very High' to 'Advisory' whenever
a county-direct health advisory is active. The model's honest band is
preserved in model_risk_band so the UI can show both signals separately.

Advisory uses a distinct purple palette and outranks every model band in
RISK_ORDER, so parent-beach worst-band aggregation surfaces official
postings over predicted Very High.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push
```

### Commit 2 — shorelife-web

```bash
cd /Users/kylechoi/shorelife-web
git status --short  # review

git add lib/{api,riskData,curated,forecastPresentation,mapPresentation}.ts \
        app/globals.css \
        components/{RiskComponents,coastal-map}.tsx \
        app/m/{utils,BeachArt}.tsx \
        "app/(desktop)/beaches/[id]/BeachDetail.tsx" \
        "app/(desktop)/research/labels/page.tsx"

git commit -m "$(cat <<'EOF'
feat(risk-band): add 'Advisory' band + explanation copy + link to county source

Beach detail now renders an explanation paragraph and 'View official advisory →'
link in the purple Advisory palette whenever a county posting is active. Map
legend, severity bar, research/labels page all include the new band. Source-link
rendering preserved for non-advisory beaches with advisory_website on file.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push
```

### Commit 3 — surf_health (band rename + data + scraper fix + retrained artifacts + docs)

```bash
cd /Users/kylechoi/surf_health
git status --short  # review carefully

# Code + tests + new alias CSV + docs
git add backend/app/schemas/domain.py \
        backend/app/ml/calibration.py \
        backend/app/repositories/serving_repository.py \
        backend/app/repositories/curated_repository.py \
        backend/scripts/fetch_county_advisories.py \
        backend/app/data/pipeline/_static_data/county_beach_name_to_station.csv \
        backend/tests/test_curated_repository.py \
        backend/tests/test_serving_snapshot_repository.py \
        CLAUDE.md \
        docs/superpowers/plans/2026-05-14-advisory-retrain-shipment.md

# Refreshed curated artifacts
git add data/curated/advisories.parquet \
        data/curated/beach_day.parquet \
        data/curated/county_advisories_report.json \
        data/curated/forecasts.parquet \
        data/curated/latest_env.parquet \
        data/curated/model_card.md \
        data/curated/serving.sqlite \
        data/curated/system_health.json \
        data/curated/advisory_audit.json

# Pre-commit safety scan
git diff --cached --name-only | grep -vE '\.(parquet|sqlite)$' | xargs grep -liE 'api[_-]?key|secret|password|bearer|sk-[a-z0-9]+|github_pat' 2>/dev/null

git commit -m "$(cat <<'EOF'
feat(advisories): clean stale records, expand aliases, rename to 'Advisory', retrain

Four coupled changes shipped atomically:

1. fetch_county_advisories.py merge_and_rebuild now treats successful
   county scrapers as authoritative — demotes ALL active records in that
   county not reaffirmed by a freshly-resolved advisory. Closes the
   "Ventura all-clear but 44 stale 2018 records persist" hole.
   192 stale records demoted, dropping active count 215 → ~52.

2. county_beach_name_to_station.csv expanded with ~13 confident aliases
   (San Mateo + Orange) from the live-page audit, capturing previously
   dropped postings. East Bay inland reservoirs deferred — they need
   roster expansion + different feature engineering.

3. risk_band 'Very High' override for advisory-active beaches renamed to
   'Advisory'. Model's honest band preserved in model_risk_band so UI
   surfaces both signals distinctly. Purple palette added; advisory
   outranks every model band in aggregation.

4. Retrained on cleaned + expanded data with all 11 models (incl. 5
   sequence models in research_models). Production winner unchanged
   (hist-gbm-curated-v0). Advisory agreement audit improves:
   - active_advisories: 49 → ~XX
   - overall agreement: 0.204 → 0.XX
   - stale pool (was 22 zero-signal records) eliminated

CV strategy docs reconciled: CLAUDE.md updated to describe the actual
temporal + spatial-holdout stack; GroupKFold + bootstrap noted as
deferred future work.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push
```

Replace `~XX` and `0.XX` in the commit message with actual post-retrain numbers from Phase 3a.

---

## Rollback

If anything regresses post-push:

```bash
cd /Users/kylechoi/surf_health
# Revert the curated artifacts to pre-cleanup snapshot
for f in advisories beach_day forecasts model_card system_health serving.sqlite advisory_audit latest_env; do
  src="data/curated/${f}.parquet.bak-pre-retrain"
  [ -f "$src" ] || src="data/curated/${f}.parquet.bak-pre-scrape"
  [ -f "$src" ] || src="data/curated/${f}.parquet.bak-pre-cleanup"
  cp "$src" "data/curated/${f}.parquet" 2>/dev/null
done
# Same pattern for .json / .md / .sqlite

git revert <commit-sha-from-step-4>
git push

# Web/mobile: git revert <their-commit-sha> && git push
```

Render auto-deploys backend on push (~3 min). Web's GitHub Pages workflow runs at 16:30 UTC daily; trigger manually via GitHub UI if you need it sooner.

---

## Deferred (not in this shipment)

Track these as separate work items:

1. **Q1 parser gaps not addressable by aliasing**:
   - San Mateo: needs station_code mapping (the page has no codes; only beach names that don't always match roster names). Outreach email sent.
   - East Bay Parks inland reservoirs (7 advisories): need decision on whether to expand roster to freshwater. Different model entirely (no marine features apply).
   - Orange: 2 Newport-Bay-shared-name stations (33rd Street Channel, Garnet Avenue Beach). Need station_code → specific_area lookup table.
   - LA: 3 sub-locations collapse onto Malibu DPH-001. Preserve sub-location in `cause` field instead of dropping.

2. **Sequence model promotion**: if the retrain confirms LSTM > hist_gbm spatially, consider promoting LSTM into `candidate_models` (currently research_models). Would mean serving sequence model predictions to users — needs latency + maintenance review.

3. **CV strategy implementation**: actual GroupKFold + 1000-bootstrap gate as previously claimed in CLAUDE.md. Real engineering work; out of scope here.

4. **Counties needing real scrapers (currently best-effort, dormant)**:
   - Monterey: returns 403 to all UAs we've tried. Likely needs a different data source (Socrata feed if available) or headless browser.
   - Santa Barbara, San Francisco: JS-rendered SPA pages return no plaintext via curl. Headless browser required.

5. **Counties with no scraper at all** (still served by state feed): Humboldt, San Luis Obispo, Sonoma. Low priority — small active counts, but worth writing if data.ca.gov continues to lag.
