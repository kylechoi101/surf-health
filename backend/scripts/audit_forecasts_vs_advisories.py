"""
Audit forecast predictions against official DPH/CalState beach advisories.

Run after each ML training step:
  python -m scripts.audit_forecasts_vs_advisories --curated data/curated/

Outputs advisory_audit.json to the curated directory with:
  - false_negatives: active advisory but model says Low/Moderate
  - false_positives: High/VeryHigh predicted but no active advisory
  - agreement_rate: fraction of advised beaches also flagged by model

The "active" advisory pool is decomposed into three sub-pools so the public-release
gate measures the right thing. California's BRD feed, in practice, contains a
mix of (1) recent fresh postings, (2) months-old geomean postings still active,
and (3) multi-year-old administrative postings issued and never lifted (Tijuana
plume, Hyperion outfall, 5y+ Bacterial Standards Violations). A blanket
"agreement rate" gate is dominated by category (3) and gives a misleading signal.

Pools (all on the *active* set):
  - acute   : started <= 14 days ago. Recent enough that the model has a fair
              chance to predict from environmental covariates. The cause field
              is *not* used for promotion to acute, because cause keywords like
              "Sewage Spill" are over-applied to multi-year admin postings.
  - chronic : started 15 - 365 days ago. Mostly geomean-based postings. The
              regulatory geomean features added to the model in early 2026
              target this pool directly; reported but not used to gate release.
  - stale   : started > 365 days ago. Almost entirely administrative postings.
              Reported with a strong note that it should not be interpreted as
              a model-quality measure.

This is a monitoring tool - the audit is never fed back as training labels
(advisories appear in features, so that would leak).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.ml.calibration import _HIGH_THRESHOLD

_RISK_ALERT_THRESHOLD = _HIGH_THRESHOLD  # synced with calibration.py risk_band()
_MIN_ADVISORY_AGREEMENT_FOR_PUBLIC_RELEASE = 0.5
_MIN_ACUTE_ADVISORIES_TO_GATE = 3  # below this many, acute pool is too noisy to gate on

_ACUTE_DURATION_DAYS = 14
_CHRONIC_DURATION_DAYS = 365


def _load(curated_dir: Path, name: str) -> pd.DataFrame:
    path = curated_dir / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _classify_pool(duration_days: float, cause: object | None = None) -> str:  # noqa: ARG001
    """Classify an advisory by its duration alone.

    The ``cause`` argument is accepted for forward compatibility but ignored:
    cause-based promotion to acute (e.g. "Sewage Spill") incorrectly captures
    decade-old admin postings that happen to carry that cause string.
    Duration is the only reliable signal we have for "this is a recent event."
    """
    if pd.isna(duration_days):
        return "unknown_duration"
    if duration_days <= _ACUTE_DURATION_DAYS:
        return "acute"
    if duration_days <= _CHRONIC_DURATION_DAYS:
        return "chronic"
    return "stale"


def _build_active_pool_lookup(advisories: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Reduce active advisories to one pool per beach_id with the strictest pool winning.

    Precedence for pool selection (most-actionable-first): acute > chronic > stale > unknown.
    A beach with multiple active advisories takes its most-actionable pool.
    """
    if advisories.empty or "status" not in advisories.columns:
        return pd.DataFrame(columns=["beach_id", "pool", "duration_days", "cause", "advisory_type"])

    active = advisories[advisories["status"] == "active"].copy()
    if active.empty:
        return pd.DataFrame(columns=["beach_id", "pool", "duration_days", "cause", "advisory_type"])

    started = pd.to_datetime(active["started_at"], errors="coerce", utc=True)
    active["duration_days"] = (now - started).dt.days
    active["pool"] = [_classify_pool(d) for d in active["duration_days"]]
    pool_rank = {"acute": 0, "chronic": 1, "stale": 2, "unknown_duration": 3}
    active["__rank"] = active["pool"].map(pool_rank).fillna(99)
    active = active.sort_values("__rank")

    keep_cols = ["beach_id", "pool", "duration_days"]
    for optional in ("cause", "advisory_type"):
        if optional in active.columns:
            keep_cols.append(optional)
    return active.drop_duplicates(subset=["beach_id"], keep="first")[keep_cols].reset_index(drop=True)


def _pool_metrics(per_beach: pd.DataFrame) -> dict[str, object]:
    advised = len(per_beach)
    if advised == 0:
        return {
            "advised_beaches": 0,
            "model_flagged": 0,
            "agreement_rate": None,
        }
    flagged = int(per_beach["model_flags_risk"].sum())
    return {
        "advised_beaches": advised,
        "model_flagged": flagged,
        "agreement_rate": round(flagged / advised, 3),
    }


def _rows(df: pd.DataFrame, n: int = 20) -> list[dict]:
    return [
        {
            "beach_id": r.beach_id,
            "risk_band": getattr(r, "risk_band", None),
            "p_exceed": round(float(r.p_exceed), 3),
            **(
                {"pool": r.pool, "advisory_age_days": int(r.duration_days) if pd.notna(r.duration_days) else None}
                if hasattr(r, "pool")
                else {}
            ),
        }
        for r in df.head(n).itertuples()
    ]


def run_audit(curated_dir: Path, *, now: pd.Timestamp | None = None) -> dict:
    forecasts = _load(curated_dir, "forecasts.parquet")
    advisories = _load(curated_dir, "advisories.parquet")

    if forecasts.empty or advisories.empty:
        return {"error": "missing forecasts or advisories", "generated_at": datetime.now(timezone.utc).isoformat()}

    if now is None:
        now = pd.Timestamp.now(tz="UTC")

    active_lookup = _build_active_pool_lookup(advisories, now=now)

    f = forecasts.drop_duplicates(subset=["beach_id"], keep="last").copy()
    f["p_exceed"] = pd.to_numeric(f["p_exceed"], errors="coerce")
    f["model_flags_risk"] = f["p_exceed"] >= _RISK_ALERT_THRESHOLD

    f = f.merge(active_lookup, on="beach_id", how="left")
    f["pool"] = f["pool"].fillna("none")
    f["has_active_advisory"] = f["pool"] != "none"

    pool_metrics: dict[str, dict] = {}
    for pool_name in ("acute", "chronic", "stale", "unknown_duration"):
        pool_metrics[pool_name] = _pool_metrics(f[f["pool"] == pool_name])

    advised_total = f[f["has_active_advisory"]]
    overall_agreement = (
        round(float(advised_total["model_flags_risk"].mean()), 3)
        if len(advised_total) > 0
        else None
    )

    fn = (
        f[f["has_active_advisory"] & ~f["model_flags_risk"]]
        .sort_values(["pool", "p_exceed"], ascending=[True, True])
    )
    fp = f[~f["has_active_advisory"] & f["model_flags_risk"]].sort_values("p_exceed", ascending=False)

    fn_by_pool = {
        pool: int((fn["pool"] == pool).sum())
        for pool in ("acute", "chronic", "stale", "unknown_duration")
    }

    return {
        "generated_at": now.isoformat() if isinstance(now, pd.Timestamp) else datetime.now(timezone.utc).isoformat(),
        "forecast_date": str(f["forecast_date"].iloc[0]) if len(f) else None,
        "model_version": str(f["model_version"].iloc[0]) if len(f) else None,
        "risk_threshold": _RISK_ALERT_THRESHOLD,
        "total_beaches": len(f),
        "active_advisories": int(len(advised_total)),
        "agreement_rate": overall_agreement,
        "pool_metrics": pool_metrics,
        "false_negatives": {
            "count": len(fn),
            "description": "Active advisory but model says Low/Moderate",
            "by_pool": fn_by_pool,
            "worst_acute": _rows(fn[fn["pool"] == "acute"]),
            "worst_chronic": _rows(fn[fn["pool"] == "chronic"]),
        },
        "false_positives": {
            "count": len(fp),
            "description": "Model says High/VeryHigh but no active advisory",
            "worst": _rows(fp),
        },
    }


def _gate_decision(audit: dict) -> tuple[bool, str | None]:
    """Return (eligible, blocker_message). eligible=True means gate passes."""
    pool_metrics = audit.get("pool_metrics") or {}
    acute = pool_metrics.get("acute") or {}
    advised = int(acute.get("advised_beaches") or 0)
    agreement = acute.get("agreement_rate")

    if advised < _MIN_ACUTE_ADVISORIES_TO_GATE:
        # Too few acute advisories on this run to assert anything; do not fail the gate.
        return True, None

    if agreement is None:
        return True, None

    if float(agreement) >= _MIN_ADVISORY_AGREEMENT_FOR_PUBLIC_RELEASE:
        return True, None

    return False, (
        "Acute advisory agreement gate failed: "
        f"{float(agreement):.3f} < {_MIN_ADVISORY_AGREEMENT_FOR_PUBLIC_RELEASE:.2f} "
        f"on {advised} acute advisories "
        f"(risk threshold p_exceed >= {_RISK_ALERT_THRESHOLD:.2f}, "
        "acute = started <= 30d or cause in {Sewage Spill, CSO, Rain})."
    )


def _apply_public_release_gate(curated_dir: Path, audit: dict) -> None:
    """Patch system_health.json promotion fields based on the acute-pool gate.

    The model is a forecast, but a public release must not contradict acute,
    recent official advisories. The chronic and stale pools (>30d old, mostly
    administrative postings) are reported for transparency but not gated on.
    """
    health_path = curated_dir / "system_health.json"
    if not health_path.exists():
        return
    try:
        payload = json.loads(health_path.read_text())
    except json.JSONDecodeError:
        return

    eligible, blocker = _gate_decision(audit)
    model_registry = payload.get("model_registry") or {}

    pool_metrics = audit.get("pool_metrics") or {}
    payload["forecast_audit"] = {
        "generated_at": audit.get("generated_at"),
        "agreement_rate": audit.get("agreement_rate"),
        "acute_agreement_rate": (pool_metrics.get("acute") or {}).get("agreement_rate"),
        "acute_advised_beaches": (pool_metrics.get("acute") or {}).get("advised_beaches"),
        "chronic_agreement_rate": (pool_metrics.get("chronic") or {}).get("agreement_rate"),
        "stale_agreement_rate": (pool_metrics.get("stale") or {}).get("agreement_rate"),
        "false_negatives": (audit.get("false_negatives") or {}).get("count"),
        "false_negatives_by_pool": (audit.get("false_negatives") or {}).get("by_pool"),
        "false_positives": (audit.get("false_positives") or {}).get("count"),
        "active_advisories": audit.get("active_advisories"),
        "risk_threshold": audit.get("risk_threshold"),
    }

    blockers = [b for b in (model_registry.get("promotion_blockers") or []) if not _is_old_agreement_blocker(b)]
    if not eligible and blocker is not None and blocker not in blockers:
        blockers.append(blocker)

    if not eligible:
        model_registry["public_release_eligible"] = False
        model_registry["deployment_stage"] = "research_prototype"
    elif not blockers:
        # No blockers anywhere: gate passes.
        model_registry["public_release_eligible"] = True
        if model_registry.get("deployment_stage") == "research_prototype":
            model_registry["deployment_stage"] = "production_candidate"

    model_registry["promotion_blockers"] = blockers
    payload["model_registry"] = model_registry
    health_path.write_text(json.dumps(payload, indent=2))


def _is_old_agreement_blocker(message: str) -> bool:
    """Match any agreement-gate blocker so reruns don't accumulate stale duplicates."""
    text = str(message or "").lower()
    return "agreement gate failed" in text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curated", required=True, type=Path, help="Path to curated data directory")
    args = parser.parse_args()

    audit = run_audit(args.curated)
    out_path = args.curated / "advisory_audit.json"
    out_path.write_text(json.dumps(audit, indent=2))
    _apply_public_release_gate(args.curated, audit)
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
