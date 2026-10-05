# Hawaii and Florida: can Shorelife expand there?

Feasibility study, 2026-10-04. Research only: no production code, workflow or `data/curated/` file changed.
Every number below is in `feasibility_results.json`. The script is `backend/scripts/multistate_feasibility.py`.

## Verdicts

| State | Verdict | Why |
|---|---|---|
| **Florida** | **Ready, once we have a live-feed scraper** | About 250 FL DOH beach sites are sampled every 7 days, year-round, with about 450 to 600 exceedance days a year. The served model carries over and beats the lookup on every metric. WQP is 9 months behind, though, and we could not read the official results page from a script. The live feed is not secured yet. |
| **Hawaii** | **Not enough data** | Hawaii DOH stopped publishing routine results after mid-2024, both in WQP and in its own export. It now publishes only the exceedances, as advisories. Exceedances are rare (1–2% of sample-days), and the model has almost no skill at telling one day from another there. |

## Florida

### Coverage in WQP (`US:12`, enterococcus, 2022-01-01 to today)

**Site filter.** WQP has 3,263 enterococcus sites in Florida. We kept 293 of them, using three rules in order:
- the WQX site type is "BEACH Program Site-*" (252 sites);
- the site type is "Ocean" (21 sites);
- the site is an estuary or bay whose name says it is a beach (20 sites).

We dropped 2,970 sites: 1,980 ambient estuary stations (1,241 of them Lee County), 640 river/stream sites, and canals and lakes. Six QC-activity results and three results with no value were also dropped. That leaves 33,505 results on 33,434 station-days.

| | All kept sites | FL DOH (`21FLDOH_WQX`) | Miami Waterkeeper (`21FLMWK_WQX`) | other 12 orgs |
|---|---|---|---|---|
| stations with ≥1 / ≥10 results | 293 / 276 | 251 / 248 | 13 / 13 | 29 / – |
| stations averaging ≥1 sample-day a month over 2022-01..2026-09 | 236 | 225 | 9 | – |
| results per year 2022 / 23 / 24 / 25 / 26 | 8,733 / 8,730 / 8,169 / 7,873 / **0** | 7,882 / 7,976 / 7,969 / 7,732 / 0 | 633 / 560 / – / – / – | small |
| sample-days per station-year, median (p25–p75) | 26 (18–50) | 26 (18–50) | 54–56 | |
| days between samples, median / p90 | 7 / 14 | 7 / 14 | 7 / 7 | |
| newest sample in WQP | **2025-12-30 (278 days ago)** | 2025-12-30 | 2023-12-12 | |
| share of stations sampled in last 30 / 90 days | 0% / 0% | 0% / 0% | 0% | |
| exceedance rate, > 70 (FL limit) / > 104 | **6.5% / 4.6%** | 5.6% / 4.0% | 24.1% / 16.7% | |
| positive sample-days 2022 / 23 / 24 / 25 | 608 / 581 / 525 / 448 (2,162 total) | 455 / 415 / 488 / 400 | 128 / 143 | |

- **Season.** Sampling runs all year. It is lighter from November to February (about 2,100–2,500 sample-days a month) than from May to August (about 3,000–3,250).
- **Units and methods.** 26,458 results are MPN (Enterolert) and 7,047 are CFU (EPA 1600 membrane filtration). There is no qPCR.
- **Censoring.** No result carries a non-detect flag, but 74% sit at or below the reported detection limit. FL DOH writes "<10" as the bare number 10 with a detection limit of 10 (also 4 and 2). Under a limit of 70, that does not change any label.
- **Other indicators** (statewide, all site types, counts only):
  - E. coli: 12–13k results a year at about 2,700 sites, mostly freshwater (2025: 5.5k; 2026: 20).
  - Fecal coliform: 3.8–4.6k results a year (2026: 0).
  - None of this is beach data, and we did not use it.

### Freshness: WQP vs the state feed

**WQP.** FL DOH beach data stops at 2025-12-30. There is no enterococcus result for any Florida site in 2026, which we checked under two characteristic names. For a daily product WQP is about 9 months behind, so it can only serve as a training archive.

**Official FL DOH results.** These appear at `floridahealth.gov/.../beach-water-quality/?County=..&SPLocation=..`, linked from the official ArcGIS "Florida Healthy Beaches Lookup" map.
- Scripted HTTP gets a **Cloudflare 403 challenge**. A text fetch returns the program text but no results, because the page renders them client-side.
- **We could not read official results, so this report has no official newest-sample date.** We did not try to get around the bot check. The Chrome tool was not connected, so we could not watch the page's network calls either.

**Official site list.** This one is machine-readable: an ArcGIS FeatureServer (`services1.arcgis.com/CY1LXxl9zlJeBuRZ/.../FloridaBeachSamplingPoints/FeatureServer/0`). It returns JSON, needs no key, and lists 419 sampling points (351 active) in 34 counties. Every point carries a STORET station ID; 246 of the 351 active points match a WQP `21FLDOH_WQX` station ID (case-insensitive). The layer holds locations only, no results.

**Unofficial evidence on freshness.** `floridahealthybeaches.com` is a privately run site that credits "Florida Health". It shows 313 sites in 31 counties:
- newest sample 2026-10-01, 3 days before today;
- median site last sampled 6 days ago;
- 65% of sites sampled in the last 7 days and 87% in the last 30;
- an advisory flag on each sample.

So FL DOH data is fresh at the source, about 9 months ahead of WQP. This site is not a candidate production feed.

**Advisories.** Per the official page, FL DOH posts advisories with the results. The trigger is a sample over 70 CFU/100 mL confirmed by a resample over 70.

### Does the served model work there?

The gate passes: 4.0 years of history and 2,162 positive sample-days.

**Setup.**
- Walk-forward with a monthly refit on every sample-day since 2023-01-01. Earlier rows have no full 365-day lookup window.
- Scored on the last 12 months with data, 2025-01..2025-12: 7,873 sample-days, 448 positives (base rate 5.7%), 250 stations.
- Training size grew from 16.9k to 24.2k rows across the refits.
- Rain coverage on scored rows was 100%.

| | AUROC | AUCPR | Brier | within-station AUROC (102 stations) |
|---|---|---|---|---|
| persistence | 0.563 | 0.089 | 0.091 | 0.492 |
| lookup | 0.795 | 0.220 | 0.048 | 0.344 |
| **logistic (served form)** | **0.816** | **0.288** | **0.046** | **0.485** |
| logistic, free season phase | 0.816 | 0.288 | 0.046 | 0.484 |
| *California served model, for reference* | *0.851* | *0.591* | *0.0766* | *0.64* |

**Logistic minus lookup, with 95% CIs from a beach-cluster bootstrap (500 reps).** Every CI excludes 0:
- AUROC +0.013 to +0.030
- AUCPR +0.042 to +0.098
- Brier −0.003 to −0.001
- within-station AUROC +0.099 to +0.176

**Coefficients across the 12 refits** (stable):

| Term | Florida | California |
|---|---|---|
| R | 0.28–0.39 | 0.37–0.41 |
| R·F | 0.26–0.42 | 0.65–0.78 |
| W | 0.38–0.42 | 0.68–0.71 |
| S | −0.13 to −0.11 | positive |
| intercept | −0.41 to −0.31 | |

**What the coefficients show.**
- The season sign flips: Florida exceedances peak in the summer wet season. The fitted cosine term picks this up on its own, and the free-phase sine term fits to about 0.
- Rain and the last result matter about half as much as in California.
- Within-station AUROC only reaches 0.49. At a single beach, the model barely ranks dirty days above clean ones, so most of its skill is telling beaches apart.

**Comparing with California.** California is scored on forward served days, every beach every day, against the next lab result. Here we score lab sample-days. The base rates differ, and AUCPR moves with the base rate, so only AUROC and within-station AUROC compare even loosely.

## Hawaii

### Coverage in WQP (`US:15`, enterococcus, 2022-01-01 to today)

Every Hawaii enterococcus site in WQP is a "BEACH Program Site-Ocean" (209) or an "Ocean" site (21). The filter dropped nothing: 230 stations, 16,674 results, 11,778 station-days. There are no QC-activity rows.

| | All | Hawaii DOH CWB (`21HI`) | City & County of Honolulu (`HI301H_WQX`) |
|---|---|---|---|
| stations with ≥1 / ≥10 results | 230 / 161 | 209 / 140 | 21 / 21 |
| stations averaging ≥1 sample-day a month over 2022-01..2026-09 | 72 | 59 | 13 |
| results per year 2022 / 23 / 24 / 25 / 26 | 5,424 / 5,420 / 3,263 / 2,208 / 359 | 3,236 / 3,237 / **901 / 0 / 1** | 2,188 / 2,183 / 2,362 / 2,208 / 358 |
| sample-days per station-year, median (p25–p75) | 2022: 14 (3–31); 2023: 12 (5–38) | 2023: 11 (4–35) | 60 (12–60) |
| days between samples, median / p90 | 7 / 28 | 8 / 35 | 4 / 16 |
| newest sample in WQP | **2026-05-13 (144 days ago)** | 2026-05-13 (a single row; routine data ends 2024-04) | 2026-02-25 |
| share of stations sampled in last 30 / 90 days | 0% / 0% | 0% / 0% | 0% / 0% |
| exceedance rate, > 130 (HI limit) / > 104 | **1.9% / 2.3%** | 1.2% / 1.6% | 3.1% / 3.5% |
| positive sample-days 2022 / 23 / 24 / 25 / 26 | 53 / 85 / 53 / 34 / 2 (227 total) | 36 / 41 / 13 / – / 0 | 17 / 44 / 40 / 34 / 2 |

- **Season.** Sampling runs all year, a little lighter in November and December.
- **Methods.**
  - DOH uses Enterolert, which is MPN, but WQP labels it "cfu/100mL".
  - Honolulu uses EPA 1600 membrane filtration (CFU).
  - There is no qPCR.
- **Censoring.** 31.6% of results are non-detects. Nearly all are Honolulu's, written as "\*Non-detect". The production `normalize_wqp_results` drops these rows, which would inflate exceedance rates; this script keeps them as clean.
- **No E. coli or fecal coliform** results in WQP for Hawaii.
- The Honolulu stations are City & County shoreline stations. We kept them because WQX types them as beach/ocean sites, but they are not the DOH advisory program.

### Freshness: WQP vs the state feed

**Hawaii DOH CWB public export.** `https://eha-cloud.doh.hawaii.gov/cwb/api/sample-test-results/csv?format=csv` is plain CSV with no auth: the "Export CSV" button of the CWB web app.
- It holds 78,251 enterococcus results going back to 2004.
- Its newest sample is **2026-10-01 (3 days old)**, but the volume collapses:
  - 3,249 / 3,256 / 1,308 results in 2022 / 23 / 24;
  - **3** in 2025;
  - 30 in 2026. Most are Kauai, starting 2026-09-14, plus a few Oahu North Shore rows. Only 6.6% of stations were sampled in the last 90 days.
- For 2022–2024 it matches WQP's `21HI` almost row for row (2022: 3,249 vs 3,236).
- **Caveat:** the lat/lon columns are swapped on every row.

**Advisories feed.** `.../cwb/api/events?format=csv` is CSV with no auth.
- Newest issued 2026-10-02.
- 51 bacteria-exceedance beach advisories in 2025 and 41 in 2026, each carrying the exceeding count.
- Also 1,146 brown-water advisories (all years).

So **DOH is still sampling** (it posts exceedances from Maui and the Big Island), **but it publishes only the exceedances.** The clean results behind them are not in the export or in WQP. A model cannot be trained or scored on exceedances alone.

**Beach list.** `.../cwb/api/beaches?format=csv` has 419 beaches: tier 1: 61, tier 2: 118, tier 3: 197, tier 4: 43.

**Other observations.**
- The old CWB "Water Quality Data" page now reads "This page is no longer available… upgrading our websites".
- The app also calls a `clinisys-samples` endpoint, which returns 401 without a login. That is probably the new lab system.

### Does the served model work there?

The gate passes on WQP (4.4 years, 227 positives). We ran three scorings because the default window is not the DOH program.

| Scoring | n / positives / stations | Model | AUROC | AUCPR | Brier | within-station AUROC |
|---|---|---|---|---|---|---|
| **WQP, last 12 months of data** (2025-06..2026-05; Honolulu stations only) | 793 / 24 / 22 | persistence | 0.457 | 0.066 | 0.049 | 0.40 |
| | | lookup | 0.527 | 0.033 | 0.030 | 0.31 |
| | | logistic | 0.714 | 0.156 | 0.028 | 0.65 (11 stations) |
| | | free phase | 0.692 | 0.112 | 0.029 | 0.63 |
| **WQP, DOH era** (2023-05..2024-04) | 4,315 / 79 / 202 | persistence | 0.458 | 0.024 | 0.035 | 0.31 |
| | | lookup | 0.623 | 0.037 | 0.018 | 0.22 |
| | | logistic | 0.635 | 0.061 | 0.019 | 0.36 (30 stations) |
| | | free phase | 0.635 | 0.066 | 0.019 | 0.35 |
| **DOH export, 2015+ history, 36 months** (2021-05..2024-04) | 9,657 / 110 / 268 | persistence | 0.545 | 0.022 | 0.021 | 0.51 |
| | | lookup | 0.661 | 0.034 | 0.011 | 0.40 |
| | | logistic | 0.685 | 0.043 | 0.011 | 0.42 (43 stations) |
| | | free phase | 0.698 | 0.043 | 0.011 | 0.44 |

**Logistic minus lookup, beach-cluster bootstrap 95% CIs.**

| Scoring | AUROC | AUCPR | Brier | within-station AUROC |
|---|---|---|---|---|
| Honolulu window | +0.09 to +0.28 | +0.06 to +0.29 | −0.003 to −0.001 | +0.19 to +0.54 |
| DOH era | −0.025 to +0.053 | −0.007 to +0.064 | 0 to +0.001 (no gain) | +0.04 to +0.23 |
| DOH export, 36 months | +0.008 to +0.040 | +0.003 to +0.022 | about 0 | −0.023 to +0.048 |

The Honolulu window has only 24 positives, so its CIs are wide.

**Coefficients.**
- **DOH export (36 refits, stable):** R 0.20–0.25, R·F 0.43–0.65, W 0.38–0.40, S 0.08–0.11. The free-phase fit gives sin −0.33 to −0.41, which puts the risk peak near early November rather than mid-January.
- **WQP DOH era:** unstable, because each fit had only 1.3k–5.2k rows. R·F ranged from −2.9 to +0.1 and W from 0.65 to 1.02.

**Reading the results.** With 1–2% of sample-days exceeding, the model ranks beaches modestly (AUROC about 0.69) but cannot pick days at a fixed beach: within-station AUROC is about 0.42, and its CI includes 0. At a base rate near 1%, AUCPR stays around 0.04. The Honolulu result looks better, but it rests on 24 positives at 11 scorable stations.

## Assumptions

- **Limits.**
  - Hawaii: 130 enterococci/100 mL. This is the CWB Beach Action Value from https://health.hawaii.gov/cwb/beach-monitoring-program/: "The CWB has adopted an EPA-recommended threshold value, called the Beach Action Value or BAV, of 130 enterococci per 100 mL".
  - Florida: 70 CFU/100 mL, from https://www.floridahealth.gov/community-environmental-public-health/environmental-public-health/water-quality/aquatic-toxins/beach-water-quality/.
  - Both states' advisories need a confirming resample. Our label is the single-sample exceedance, the same as California's `exceeds_stv`.
  - Any qPCR row would have been judged at 1,413 copies, but there were none.
- **Labels.** One label per station-day: the worst result of the day. Non-detects count as clean.
- **Lookup.** `(pos + 5g)/(n + 5)` over the 365 days strictly before D, with g the pooled rate of the state's kept sites over the same window. It is computed with the served model's own `logit_challenger.lab_history_features`, so R (log10 of result over limit, clipped at 0.01) and F (exp(−(age−1)/3)) match production.
- **Training rows.** Only rows with a full 365-day lookup window behind them: from 2023-01-01 for WQP, and from 2016-01-01 for the Hawaii export run.
- **Rain.** The Open-Meteo archive (best-match model), hourly precipitation in local time, summed over [D−3 05:00, D 05:00). One request per 0.1° coordinate, using the WQP station coordinates and not hydrologic pour points (California uses pour points).
  - For Florida we fetched rain from 2022-12-25 only, which is why 74% of all Florida sample-days have rain. Coverage of training and scored rows is 100%.
- **Season.** S = cos(2π(doy−15)/365.25). The free-phase model adds the matching sine.
- **Within-station AUROC.** Uses production's `within_beach_auroc`: row-weighted, stations with ≥20 rows and both outcomes. In Hawaii only 11–43 stations qualify.
- **Persistence.** 1 if the last in-window result exceeded, else g.
- **What "today" means.** Freshness is measured against 2026-10-04. WQP pulls ran 2026-10-04 18:16–18:36 local, and the Hawaii exports at 01:17 UTC on 2026-10-05.

## Not verified

- **Florida official results:** newest sample date, site count and format. The page was blocked to scripts by Cloudflare (403), and the browser tool was unavailable. The freshness figures come from an unofficial mirror.
- **Whether FL DOH has a bulk results download or API.** None was found. The ArcGIS layers we found hold locations only.
- **Hawaii:** why routine results stopped after mid-2024, and whether the September 2026 Kauai rows are a restart. Is the Clinisys endpoint going to be public? We did not contact DOH.
- **Hawaii WQP `21HI` units** say cfu/100mL for an MPN method. We treated the values as numbers against 130 either way.
- **California comparison:** we did not rerun California on sample-days with this exact harness. The CA numbers are quoted from CLAUDE.md.

## Reproduce

```
cd backend
python scripts/multistate_feasibility.py fetch    --state HI   # WQP, cached per quarter in data/raw/wqp/
python scripts/multistate_feasibility.py rain     --state HI   # Open-Meteo, cached per 0.1° coord
python scripts/multistate_feasibility.py analyze  --state HI   # Part 1 + Part 3 -> feasibility_results.json
python scripts/multistate_feasibility.py hi-cwb   --state HI   # DOH export coverage + 2015+ model run
python scripts/multistate_feasibility.py feeds    --state HI   # Part 2 summary from cached exports
# same for --state FL (no hi-cwb)
```

- The Hawaii exports (`data/raw/hi_cwb/`) and the Florida sampling-points layer and mirror pages (`data/raw/fl_doh/`, `data/raw/fl_thirdparty/`) were fetched by hand with curl, from the URLs above.
- `data/raw/` is gitignored and was not committed.
- The normalized sample-days (`*_wqp_sample_days.parquet`) and the walk-forward predictions (`*_walkforward_predictions.parquet`) are committed beside this report.
