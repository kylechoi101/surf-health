# Lookup Baseline vs. Served ML Model Backtest Report

## Executive Summary
This report evaluates the standalone **lookup baseline forecaster** against the **served ML model** using historical forecast logs (`forecast_history.parquet`) and official water quality monitoring results (`beach_day.parquet`).

Predictions are evaluated against the first lab result observed strictly forward within 1 to 3 days ($D+1 \dots D+3$, `exceeds_stv`).

Across all evaluated slices, the simple lookup baseline (strictly-prior 365-day per-beach history with Bayesian shrinkage) demonstrates superior discrimination (AUROC, AUCPR) and probability calibration (Brier score) compared to the served ML model.

## Slices Performance

| Slice | N | Base Rate | AUROC (Lookup) | AUROC (ML) | AUCPR (Lookup) | AUCPR (ML) | Brier (Lookup) | Brier (ML) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| All rows | 18,548 | 0.0936 | 0.8666 | 0.8053 | 0.5715 | 0.3376 | 0.0601 | 0.0759 |
| Last 90 days | 11,616 | 0.0961 | 0.8775 | 0.8238 | 0.5791 | 0.3946 | 0.0604 | 0.0713 |
| Last 30 days | 3,396 | 0.1249 | 0.8871 | 0.8462 | 0.6410 | 0.5424 | 0.0691 | 0.0771 |
| Culture beaches | 15,235 | 0.0556 | 0.8016 | 0.7773 | 0.2333 | 0.1801 | 0.0503 | 0.0590 |
| ddPCR beaches | 3,313 | 0.2686 | 0.8991 | 0.8140 | 0.7911 | 0.6323 | 0.1051 | 0.1537 |

## Per-Beach Evaluation Summary

The lookup baseline makes no within-beach claim; it only ranks beaches against each other across the monitoring network. Within any single beach, the 365-day rate is nearly constant day to day, so its within-beach AUROC measures window drift rather than skill.

To evaluate whether the served ML model possesses day-to-day predictive skill within individual beaches, we evaluate the ML's within-beach AUROC on its own across all qualifying beaches (≥10 verifiable samples with both positive and negative outcomes present, 164 beaches total) against a within-beach persistence baseline (`last_sample_exceeds` as the score):

| Predictor | Mean AUROC | Median AUROC | Beaches AUROC > 0.5 | Beaches AUROC ≤ 0.5 |
| --- | --- | --- | --- | --- |
| Served ML | 0.5133 | 0.5334 | 90 (54.9%) | 74 (45.1%) |
| Persistence Baseline (`last_sample_exceeds`) | 0.4924 | 0.4783 | 33 (20.1%) | 131 (79.9%) |

- **Served ML Model**: mean AUROC = 0.5133, median AUROC = 0.5334; 90 beaches > 0.5 vs. 74 beaches ≤ 0.5. The mean near 0.50 demonstrates that the ML model's day-to-day movement within a beach carries negligible predictive information on this window.
- **Persistence Baseline**: mean AUROC = 0.4924, median AUROC = 0.4783; 33 beaches > 0.5 vs. 131 beaches ≤ 0.5.

Full beach-by-beach metrics are exported to `backtest_by_beach.csv`.

### Top 25 Beaches by Volume of Verifiable Samples

| Beach ID | Beach Name | County | N | Positives | AUROC (ML) | AUROC (Persistence) |
| --- | --- | --- | --- | --- | --- | --- |
| ca134387-san-diego-north-imperial-beach-ib-060 | Carnation Ave. | San Diego | 148 | 139 | 0.5344 | 0.5931 |
| ca068221-san-diego-imperial-beach-municipal-beach-other-ib-050 | End of Seacoast Dr | San Diego | 147 | 138 | 0.4537 | 0.4674 |
| ca674364-los-angeles-inner-cabrillo-beach-cb-02 | CB-02 | Los Angeles | 141 | 64 | 0.4343 | 0.4732 |
| ca674364-los-angeles-inner-cabrillo-beach-cb-01 | CB-01 | Los Angeles | 141 | 8 | 0.5150 | 0.4737 |
| ca735620-los-angeles-santa-monica-state-beach-smb-3-3 | Santa Monica Pier | Los Angeles | 140 | 40 | 0.5003 | 0.5850 |
| ca643858-los-angeles-malibu-lagoon-state-beach-smb-mc-2 | SMB-MC-2 | Los Angeles | 140 | 4 | 0.6443 | 0.4890 |
| ca604254-san-diego-coronado-north-beach-eh-060 | Navy Fence (A) | San Diego | 131 | 81 | 0.6140 | 0.6548 |
| ca624767-san-diego-harbor-beach-oc-100 | San Luis Rey River outlet | San Diego | 93 | 11 | 0.6203 | 0.4817 |
| ca316627-san-diego-dog-beach-o-b-fm-010 | San Diego River outlet | San Diego | 88 | 21 | 0.3696 | 0.3252 |
| ca876094-san-diego-la-jolla-shores-beach-fm-080 | Ave De La Playa | San Diego | 82 | 36 | 0.3508 | 0.3273 |
| ca279698-long-beach-city-long-beach-b-60 | Molino Ave-Beach | Los Angeles | 80 | 8 | 0.5365 | 0.4583 |
| ca531242-san-diego-san-dieguito-river-beach-eh-380 | San Dieguito River outlet | San Diego | 78 | 15 | 0.7360 | 0.4524 |
| ca279698-long-beach-city-long-beach-b-56 | 10th Place-Beach | Los Angeles | 77 | 13 | 0.3377 | 0.5222 |
| ca785240-san-diego-torrey-pines-state-beach-fm-100 | Los Penasquitos Lagoon | San Diego | 76 | 7 | 0.3478 | 0.4855 |
| ca279698-long-beach-city-long-beach-b-7 | Coronado Ave-Beach | Los Angeles | 76 | 13 | 0.6703 | 0.4683 |
| ca279698-long-beach-city-long-beach-b-5 | 5th Place-Beach | Los Angeles | 71 | 13 | 0.6340 | 0.4609 |
| ca279698-long-beach-city-long-beach-b-8 | W/side of Belmont Pier | Los Angeles | 68 | 8 | 0.6104 | 0.4833 |
| ca506450-san-diego-san-diego-bay-eh-070 | Tidelands Park | San Diego | 68 | 25 | 0.4772 | 0.4488 |
| ca957734-santa-barbara-gaviota-state-beach-wp0000079 | WP0000079 | Santa Barbara | 68 | 14 | 0.3915 | 0.4153 |
| ca506450-san-diego-san-diego-bay-eh-200 | Shelter Is shoreline park | San Diego | 67 | 17 | 0.4471 | 0.4094 |
| ca976061-san-diego-buccaneer-beach-oc-022 | Loma Alta Creek outlet | San Diego | 67 | 4 | 0.8968 | 0.4683 |
| ca880471-santa-cruz-capitola-city-beach-o240 | Capitola Beach west of Jetty | Santa Cruz | 67 | 13 | 0.7906 | 0.6275 |
| ca905766-santa-cruz-main-beach-o450 | Main Beach at San Lorenzo | Santa Cruz | 66 | 6 | 0.3806 | 0.4833 |
| ca218180-santa-barbara-east-beach-wp0000085 | East Beach- Mission Creek | Santa Barbara | 66 | 6 | 0.6458 | 0.7167 |
| ca326620-san-diego-moonlight-beach-eh-420 | Cottonwood Creek outlet | San Diego | 66 | 6 | 0.2861 | 0.4833 |
