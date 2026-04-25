"""
Audit forecast predictions against official DPH/CalState beach advisories.

Run after each ML training step:
  python -m scripts.audit_forecasts_vs_advisories --curated data/curated/

Outputs advisory_audit.json to the curated directory with:
  - false_negatives: active advisory but model says Low/Moderate
  - false_positives: High/VeryHigh predicted but no active advisory
  - agreement_rate: fraction of advised beaches also flagged by model

This is a monitoring tool — the audit is never fed back as training labels
(advisories appear in features, so that would leak).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


_RISK_ALERT_THRESHOLD = 0.45  # risk_band boundary between Moderate and High


def _load(curated_dir: Path, name: str) -> pd.DataFrame:
    path = curated_dir / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def run_audit(curated_dir: Path) -> dict:
    forecasts = _load(curated_dir, "forecasts.parquet")
    advisories = _load(curated_dir, "advisories.parquet")

    if forecasts.empty or advisories.empty:
        return {"error": "missing forecasts or advisories", "generated_at": datetime.now(timezone.utc).isoformat()}

    active = advisories[advisories["status"] == "active"][["beach_id"]].drop_duplicates()
    active_ids = set(active["beach_id"].tolist())

    # One row per beach (deduplicate multi-date forecasts, keep latest)
    f = forecasts.drop_duplicates(subset=["beach_id"], keep="last").copy()

    f["has_active_advisory"] = f["beach_id"].isin(active_ids)
    f["model_flags_risk"] = f["p_exceed"] >= _RISK_ALERT_THRESHOLD

    # False negatives: active advisory but model says safe
    fn = f[f["has_active_advisory"] & ~f["model_flags_risk"]].sort_values("p_exceed")
    # False positives: model flags risk but no active advisory
    fp = f[~f["has_active_advisory"] & f["model_flags_risk"]].sort_values("p_exceed", ascending=False)
    # True positives: model and advisory agree on risk
    tp = f[f["has_active_advisory"] & f["model_flags_risk"]]

    n_advised = len(f[f["has_active_advisory"]])
    agreement_rate = len(tp) / n_advised if n_advised > 0 else None

    def _rows(df: pd.DataFrame, n: int = 20) -> list[dict]:
        return [
            {
                "beach_id": r.beach_id,
                "risk_band": r.risk_band,
                "p_exceed": round(float(r.p_exceed), 3),
            }
            for r in df.head(n).itertuples()
        ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "forecast_date": str(f["forecast_date"].iloc[0]) if len(f) else None,
        "model_version": str(f["model_version"].iloc[0]) if len(f) else None,
        "total_beaches": len(f),
        "active_advisories": n_advised,
        "agreement_rate": round(agreement_rate, 3) if agreement_rate is not None else None,
        "false_negatives": {
            "count": len(fn),
            "description": "Active advisory but model says Low/Moderate",
            "worst": _rows(fn),
        },
        "false_positives": {
            "count": len(fp),
            "description": "Model says High/VeryHigh but no active advisory",
            "worst": _rows(fp),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curated", required=True, type=Path, help="Path to curated data directory")
    args = parser.parse_args()

    audit = run_audit(args.curated)
    out_path = args.curated / "advisory_audit.json"
    out_path.write_text(json.dumps(audit, indent=2))
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
