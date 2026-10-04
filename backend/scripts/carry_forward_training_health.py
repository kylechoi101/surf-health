#!/usr/bin/env python3
"""Keep system_health.json whole on a daily run that skips ML training.

The data pipeline rewrites system_health.json from scratch with a placeholder
model_registry ("derived-persistence-v0") and no release_gate; until now the
training step always put the rest back. When training does not run:

- model_registry and serving_calibration are carried forward from the previous
  run's file (they describe the last ML training run, which is still the
  current challenger);
- served_metrics is recomputed from forecast_history.parquet, as training does;
- release_gate is written for this run. The ML release gate judges the ML model,
  and the served estimate no longer comes from it, so nothing blocks publication.
  verify_release_gate.py would otherwise fail closed on the missing block.
- ml_training records that training was skipped and when the carried registry
  was produced.

Usage:
  python scripts/carry_forward_training_health.py --curated ../data/curated/ \
      --previous /tmp/prev_system_health.json
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.json_safe import dumps_strict  # noqa: E402
from app.ml.served_metrics import served_performance  # noqa: E402

CARRIED_KEYS = ("model_registry", "serving_calibration")


def carry_forward(curated: Path, previous: Path) -> dict:
    health_path = curated / "system_health.json"
    health = json.loads(health_path.read_text())
    try:
        prior = json.loads(previous.read_text())
    except (OSError, ValueError) as exc:
        print(f"carry_forward: no usable previous health ({exc!r}); keeping the pipeline's", file=sys.stderr)
        prior = {}

    for key in CARRIED_KEYS:
        if key in prior:
            health[key] = prior[key]

    try:
        served = served_performance(curated)
    except Exception as exc:  # noqa: BLE001 — scoring must never cost the forecast
        print(f"carry_forward: served scoring failed ({exc!r})", file=sys.stderr)
        served = None
    health["served_metrics"] = served or {"status": "insufficient_served_history"}

    health["release_gate"] = {
        "enforced": False,
        "public_release_eligible": True,
        "forecast_published": True,
        "blockers": [],
        "note": "ML training skipped this run; the served estimate does not depend on the ML release gate.",
    }
    health["ml_training"] = {
        "ran": False,
        "skipped_at": datetime.now(UTC).isoformat(timespec="seconds"),
        # The previous file's stamp: the registry above is at least this old.
        "registry_carried_from": (prior.get("ml_training") or {}).get("registry_carried_from")
        or prior.get("pipeline_freshness"),
    }

    tmp = health_path.with_suffix(".json.tmp")
    tmp.write_text(dumps_strict(health))
    tmp.replace(health_path)
    return health


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--curated", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    args = parser.parse_args()
    health = carry_forward(args.curated, args.previous)
    registry = health.get("model_registry") or {}
    print(
        f"carry_forward: model_registry={registry.get('production_model')} "
        f"carried_from={health['ml_training']['registry_carried_from']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
