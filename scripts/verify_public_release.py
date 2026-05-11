#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> object:
    return json.loads(path.read_text())


def _fail(message: str) -> None:
    print(f"public-release check failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def _risk_band(probability: float) -> str:
    if probability < 0.20:
        return "Low"
    if probability < 0.30:
        return "Moderate"
    if probability < 0.70:
        return "High"
    return "Very High"


def _check_model_health() -> None:
    health = _load_json(ROOT / "data" / "curated" / "system_health.json")
    registry = health.get("model_registry") if isinstance(health, dict) else None
    if not isinstance(registry, dict):
        _fail("system_health.json is missing model_registry")
    if registry.get("public_release_eligible") is not True:
        _fail("model_registry.public_release_eligible is not true")
    blockers = registry.get("promotion_blockers") or []
    if blockers:
        _fail(f"promotion blockers remain: {blockers}")
    if not registry.get("spatial_metrics"):
        _fail("spatial metrics are missing")

    audit = health.get("forecast_audit") if isinstance(health, dict) else None
    if not isinstance(audit, dict):
        _fail("system_health.json is missing forecast_audit")
    false_negatives = audit.get("false_negatives_by_pool") or {}
    if false_negatives.get("acute", 0) != 0:
        _fail("acute advisory false negatives remain")
    if false_negatives.get("chronic", 0) != 0:
        _fail("chronic advisory false negatives remain")

    model_card = (ROOT / "data" / "curated" / "model_card.md").read_text()
    match = re.search(r"Active-advisory agreement rate.*: ([0-9.]+)", model_card)
    if not match:
        _fail("model_card.md is missing the advisory agreement rate")
    card_rate = float(match.group(1))
    audit_rate = float(audit.get("agreement_rate"))
    if round(card_rate, 3) != round(audit_rate, 3):
        _fail(f"model_card advisory rate {card_rate} does not match audit {audit_rate}")


def _check_static_advisory_payload() -> None:
    beaches = _load_json(ROOT / "web" / "public" / "data" / "beaches.json")
    if not isinstance(beaches, list):
        _fail("web public beaches payload is not a list")

    adjusted = [
        beach
        for beach in beaches
        if isinstance(beach, dict)
        and isinstance(beach.get("forecast"), dict)
        and beach["forecast"].get("advisory_floor_applied") is True
    ]
    if not adjusted:
        return

    for beach in adjusted:
        forecast = beach["forecast"]
        raw = forecast.get("p_exceed_raw")
        served = forecast.get("p_exceed")
        if not isinstance(raw, (int, float)):
            _fail(f"{beach.get('id')} is missing numeric p_exceed_raw")
        if not isinstance(served, (int, float)):
            _fail(f"{beach.get('id')} is missing numeric p_exceed")
        if raw >= served:
            _fail(f"{beach.get('id')} raw probability is not below advisory-adjusted display")
        expected_band = _risk_band(float(raw))
        if forecast.get("model_risk_band") != expected_band:
            _fail(
                f"{beach.get('id')} model_risk_band={forecast.get('model_risk_band')} "
                f"does not match raw probability band {expected_band}"
            )
        if forecast.get("official_advisory_active") is not True:
            _fail(f"{beach.get('id')} advisory floor is present without official advisory flag")
        if forecast.get("forecast_label_mode") != "official_advisory_override":
            _fail(f"{beach.get('id')} advisory forecast is not labeled as an official override")


def main() -> None:
    _check_model_health()
    _check_static_advisory_payload()
    print("public-release checks passed")


if __name__ == "__main__":
    main()
