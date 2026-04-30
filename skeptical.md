# Skeptical Launch Assessment - Shorelife

Updated: 2026-04-30

## Overall Grade: B- for web, C for mobile/API launch readiness

Shorelife is no longer a toy. The web product is real, the public model artifacts now agree on
`stacked-ensemble-curated-v0`, and the daily forecast framing is much more honest than the earlier
"real-time" posture. But it should not be publicly launched as a dependable health clearance today.
The next 10 hours should be spent on reliability, risk communication, and mobile fit-and-finish, not
on another model architecture pass.

## What Is Working

- The live GitHub Pages web routes respond with HTTP 200 for the homepage and methodology page.
- `data/curated/system_health.json`, `data/curated/model_version.json`, and
  `data/curated/model_card.md` agree on `stacked-ensemble-curated-v0`.
- The model beats persistence in the current quick spatial backtest:
  - county AUCPR 0.367 vs persistence 0.172
  - beach AUCPR 0.347 vs persistence 0.241
- The product now mostly describes itself as a daily forecast and decision-support tool, not a
  real-time safety clearance.
- Unsupported stations are represented as unsupported instead of showing the
  `derived-persistence-v0` fallback as if it were a production model.
- The strongest model features are biologically plausible: UV/solar inactivation, shore-normal wind,
  pier/estuary proximity, and days since sunny.

## What Is Bad

- The Render API is not launch-stable. On 2026-04-30, `/system/health` initially responded, but a
  beach observations request returned 502 and subsequent API routes returned 503. That is a hard
  blocker for mobile.
- Root cause is memory pressure in per-beach parquet reads. `beach_day.parquet` is about 11 MB on
  disk but expands to about 510 MB when all 62 columns are materialized. It has one row group, so
  filtering by `beach_id` does not protect the Render free-tier process enough if all columns are
  requested.
- Current coverage is only 377 of 924 monitored stations, or 40.8%. That is acceptable only if the
  UI keeps unsupported beaches neutral and obvious.
- Absolute model skill is still modest. The model is useful as a planning signal, not as a "go in the
  water" guarantee.
- Low-base-rate counties can still suffer from false positives and alert fatigue. Do not ship push
  alerts until precision, recall, and calibration are reported by county/base rate.
- The mobile header still uses the tiny app icon as a 20 px inline logo, which makes the brand look
  unfinished.
- The mobile app has not gone through TestFlight burn-in, App Store Connect privacy review, or real
  device share/route QA.
- The custom domain is still not live, so public share URLs look like a personal GitHub Pages path.

## Suggested 10-Hour Solution

1. Ship the backend memory fix first.
   - Keep per-beach parquet reads column-narrow.
   - Redeploy Render.
   - Smoke `/system/health`, `/beaches`, `/parent-beaches`, one forecast route, and five repeated
     observation-route hits.

2. Upgrade Render from free to Starter before TestFlight traffic.
   - The code fix reduces the spike, but the free tier remains too tight for public-health UX.

3. Fix the mobile logo.
   - Create `mobile/assets/lockup.png` from the existing Shorelife logo source.
   - Replace the 20 px app icon in `mobile/app/(tabs)/index.tsx`.
   - Verify home/search/map tabs on simulator or device.

4. Freeze model/copy claims.
   - Allowed: "daily forecast", "decision support", "latest official sample", "check posted
     advisories".
   - Avoid: "safe", "real-time", "nowcast", "clearance", "guaranteed".

5. Run one release smoke.
   - Web build.
   - Backend targeted tests.
   - Mobile TypeScript check.
   - API route smoke after deploy.
   - Manual share-card/iMessage check.

## What Top Operators Would Do Next

- Design/UX: make uncertainty first-class. Show official advisory status and model coverage before
  probability. Do not bury limitations in methodology.
- Model: move from statewide proxy modeling toward beach-specific or drainage-area models with
  runoff, outfall, turbidity, and advisory-reason signals.
- Artifacts: publish a short model card, data card, changelog, route smoke log, and calibration page
  that all use the same model version and validation snapshot.
- Operations: treat public API health as a product feature. Add uptime checks and a public status
  note before user acquisition.
- Growth: get one beach community or local water-quality partner to trust the artifact. For this
  field, credibility beats generic launch volume.

