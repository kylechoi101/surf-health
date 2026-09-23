# Lookup Baseline vs. Served ML Forecast Comparison: 2026-09-22

## Overview
This comparison evaluates the served ML model (`forecasts.parquet`, 402 served beaches) against the strictly-prior lookup baseline (`lookup_forecast_2026-09-22.parquet`) on forecast date **2026-09-22**.

## (a) Summary Count Table: Served Risk Band × Lookup Band

| Served Risk Band | Elevated | Low | Posted | Unmonitored | Total |
| --- | --- | --- | --- | --- | --- |
| High | 24 | 1 | 14 | 0 | 39 |
| Low | 92 | 227 | 0 | 22 | 341 |
| Moderate | 18 | 0 | 0 | 0 | 18 |
| Very High | 4 | 0 | 0 | 0 | 4 |
| Total | 138 | 228 | 14 | 22 | 402 |

## (b) Unmonitored Beaches Served by ML

The served ML model produces forecasts for **22** beaches that the lookup baseline identifies as **Unmonitored** (no lab sample within the last 30 days, or never sampled).

## (c) Top 25 Largest Discrepancies (|p_exceed - p_lookup|)

| Rank | Beach Name | County | Served Band | Lookup Band | Served p_exceed | Lookup p_lookup | \|Diff\| | Sample Age (days) | Last Sample Date | Last Sample Exceeds | Last Sample Value (MPN or copies/100ml) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Silver Strand - Guard Shack | San Diego | Moderate | Elevated | 0.257 | 0.814 | 0.557 | 2 | 2026-09-20 | No | 545.0 |
| 2 | Avenida Lunar | San Diego | High | Elevated | 0.300 | 0.684 | 0.384 | 2 | 2026-09-20 | No | 217.0 |
| 3 | Castle Rock SD | Los Angeles | Low | Elevated | 0.065 | 0.427 | 0.363 | 6 | 2026-09-16 | No | 10.0 |
| 4 | Glorietta Bay | San Diego | Low | Elevated | 0.065 | 0.355 | 0.290 | 4 | 2026-09-18 | No | 262.0 |
| 5 | San Diego River outlet | San Diego | Low | Elevated | 0.065 | 0.348 | 0.284 | 5 | 2026-09-17 | No | 423.0 |
| 6 | Loma Ave (frmrly Isabella | San Diego | High | Elevated | 0.481 | 0.761 | 0.279 | 8 | 2026-09-14 | No | 419.0 |
| 7 | Erckenbrack Park, at beach | San Mateo | High | Elevated | 0.684 | 0.410 | 0.275 | 8 | 2026-09-14 | No | 30.0 |
| 8 | DILLON | Marin | High | Posted | 0.300 | 0.027 | 0.273 | 8 | 2026-09-14 | No | 10.0 |
| 9 | Escondido Creek | Los Angeles | Low | Elevated | 0.065 | 0.327 | 0.262 | 7 | 2026-09-15 | No | 10.0 |
| 10 | Topanga Beach | Los Angeles | Low | Elevated | 0.013 | 0.266 | 0.253 | 3 | 2026-09-19 | No | 10.0 |
| 11 | Santa Monica Canyon on Will Rogers State Beach | Los Angeles | Low | Elevated | 0.020 | 0.272 | 0.252 | 3 | 2026-09-19 | No | 10.0 |
| 12 | West of the pier | Los Angeles | High | Posted | 0.300 | 0.054 | 0.246 | 5 | 2026-09-17 | No | 10.0 |
| 13 | 10000 | Ventura | High | Low | 0.300 | 0.057 | 0.243 | 8 | 2026-09-14 | No | 10.0 |
| 14 | End of Seacoast Dr | San Diego | High | Elevated | 0.684 | 0.926 | 0.241 | 2 | 2026-09-20 | Yes | 1685.0 |
| 15 | Imperial Beach Pier | San Diego | Very High | Elevated | 0.709 | 0.948 | 0.238 | 2 | 2026-09-20 | No | 902.0 |
| 16 | Lifeguard Tower | Los Angeles | Low | Elevated | 0.065 | 0.302 | 0.237 | 3 | 2026-09-19 | No | 20.0 |
| 17 | local name = surf-west point avenue | San Mateo | Low | Elevated | 0.069 | 0.306 | 0.237 | 8 | 2026-09-14 | No | 20.0 |
| 18 | Cortez Ave | San Diego | Very High | Elevated | 0.700 | 0.936 | 0.236 | 2 | 2026-09-20 | Yes | 1752.0 |
| 19 | Playas Blanca MEX | San Diego | Very High | Elevated | 0.930 | 0.696 | 0.234 | 28 | 2026-08-25 | Yes | 280.0 |
| 20 | Fanuel Park | San Diego | Low | Elevated | 0.065 | 0.290 | 0.226 | 6 | 2026-09-16 | No | 662.0 |
| 21 | Carnation Ave. | San Diego | Very High | Elevated | 0.709 | 0.924 | 0.215 | 2 | 2026-09-20 | No | 1174.0 |
| 22 | OC-110 | San Diego | High | Posted | 0.300 | 0.092 | 0.208 | 8 | 2026-09-14 | No | 195.0 |
| 23 | Ramirez Creek | Los Angeles | Low | Elevated | 0.065 | 0.270 | 0.206 | 28 | 2026-08-25 | No | 10.0 |
| 24 | Linda Mar Beach # 555 | San Mateo | High | Elevated | 0.684 | 0.489 | 0.196 | 8 | 2026-09-14 | No | 31.0 |
| 25 | WP0000037 | Santa Barbara | High | Posted | 0.300 | 0.105 | 0.195 | 8 | 2026-09-14 | No | 52.0 |
