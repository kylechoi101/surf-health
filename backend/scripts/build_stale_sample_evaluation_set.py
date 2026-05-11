from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.ml.stale_evaluation import build_serving_stale_sample_set, build_stale_prior_router


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the current serving set of beaches with enough history and stale samples."
    )
    parser.add_argument("--curated-dir", type=Path, default=_repo_root() / "data" / "curated")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--reference-date", default=None)
    parser.add_argument("--stale-cutoff-days", type=int, default=50)
    parser.add_argument("--min-samples", type=int, default=100)
    parser.add_argument("--min-positives", type=int, default=10)
    parser.add_argument("--min-county-samples", type=int, default=50)
    parser.add_argument("--min-county-positives", type=int, default=5)
    args = parser.parse_args()

    curated_dir = args.curated_dir
    forecasts = pd.read_parquet(curated_dir / "forecasts.parquet")
    reference_date = args.reference_date or str(pd.to_datetime(forecasts["forecast_date"]).max().date())
    beaches = pd.read_parquet(curated_dir / "beaches.parquet")
    observations = pd.read_parquet(curated_dir / "observations.parquet")
    stale_set = build_serving_stale_sample_set(
        beaches,
        observations,
        forecasts=forecasts,
        reference_date=reference_date,
        stale_cutoff_days=args.stale_cutoff_days,
        min_samples=args.min_samples,
        min_positives=args.min_positives,
    )
    stale_routes = build_stale_prior_router(
        stale_set,
        observations,
        min_beach_samples=args.min_samples,
        min_beach_positives=args.min_positives,
        min_county_samples=args.min_county_samples,
        min_county_positives=args.min_county_positives,
    )

    output_dir = args.output_dir or (
        curated_dir / "diagnostics" / f"stale_sample_set_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "serving_stale_sample_candidates.csv"
    routes_path = output_dir / "serving_stale_prior_routes.csv"
    summary_path = output_dir / "summary.json"
    stale_set.to_csv(csv_path, index=False)
    stale_routes.to_csv(routes_path, index=False)
    route_counts = stale_routes["stale_route"].value_counts().to_dict() if not stale_routes.empty else {}
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "reference_date": reference_date,
        "stale_cutoff_days": args.stale_cutoff_days,
        "min_samples": args.min_samples,
        "min_positives": args.min_positives,
        "candidate_count": int(len(stale_set)),
        "forecast_available_count": int(stale_set["forecast_available"].sum())
        if "forecast_available" in stale_set.columns
        else 0,
        "route_counts": {str(route): int(count) for route, count in route_counts.items()},
        "outputs": {
            "serving_stale_sample_candidates": str(csv_path),
            "serving_stale_prior_routes": str(routes_path),
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"summary": str(summary_path), **summary}, indent=2))


if __name__ == "__main__":
    main()
