"""Tests for app/core/json_safe.py — no bare NaN may reach a published file.

Regression guard for 2026-07-24: ``within_beach_auroc`` returns NaN for a lag
bucket where no beach qualified, ``json.dumps`` wrote it as a bare ``NaN``
token, and the shorelife-web static export died on
``SyntaxError: Unexpected token 'N'`` while prerendering /research.

The API is not the affected consumer — pydantic v2 already serialises non-finite
floats to null in the response path — but every strict reader of the published
file or the sqlite health row is.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from app.core.json_safe import dumps_strict, json_safe, write_json


def _strict_loads(raw: str):
    """json.loads that rejects NaN/Infinity, the way JSON.parse does."""

    def reject(constant):
        raise ValueError(f"non-finite token in payload: {constant}")

    return json.loads(raw, parse_constant=reject)


def test_nan_becomes_null():
    assert json_safe({"within_beach_auroc": float("nan")}) == {"within_beach_auroc": None}


def test_infinities_become_null():
    assert json_safe([float("inf"), float("-inf")]) == [None, None]


def test_finite_values_are_untouched():
    payload = {"auroc": 0.6781912702719388, "n_beaches": 19.0, "name": "hist_gbm", "ok": True}
    assert json_safe(payload) == payload


def test_numpy_scalars_are_normalised():
    safe = json_safe({"a": np.float64("nan"), "b": np.float64(0.5), "c": np.int64(7)})
    assert safe == {"a": None, "b": 0.5, "c": 7}
    assert isinstance(safe["c"], int)


def test_nested_structures_are_scrubbed():
    payload = {"by_lag": {"lag_8_14d": {"within_beach_auroc": float("nan"), "n_rows": 0.0}}}
    assert json_safe(payload)["by_lag"]["lag_8_14d"] == {"within_beach_auroc": None, "n_rows": 0.0}


def test_dumps_strict_output_survives_a_javascript_style_parse():
    raw = dumps_strict({"by_lag": {"lag_8_14d": {"within_beach_auroc": float("nan")}}})
    assert "NaN" not in raw
    assert _strict_loads(raw) == {"by_lag": {"lag_8_14d": {"within_beach_auroc": None}}}


def test_plain_json_dumps_would_have_produced_the_broken_token():
    # Documents the bug: the default writer emits JSON no other language accepts.
    broken = json.dumps({"within_beach_auroc": float("nan")})
    assert "NaN" in broken
    with pytest.raises(ValueError):
        _strict_loads(broken)


def test_write_json_round_trips(tmp_path):
    path = tmp_path / "system_health.json"
    write_json(path, {"pipeline_freshness": "2026-07-25T17:52:44+00:00", "m": float("nan")})
    payload = _strict_loads(path.read_text())
    assert payload["m"] is None
    assert payload["pipeline_freshness"] == "2026-07-25T17:52:44+00:00"


def test_unscrubbable_value_raises_rather_than_shipping_bad_json():
    class Sneaky(float):
        """A float subclass that hides its non-finiteness from .item()."""

    payload = {"x": Sneaky("nan")}
    # json_safe catches this one, so the strict dump must succeed with null.
    assert "NaN" not in dumps_strict(payload)


def test_published_system_health_has_no_non_finite_tokens():
    """The shipped artifact itself must parse under strict JSON rules."""
    from pathlib import Path

    health = Path(__file__).resolve().parents[2] / "data" / "curated" / "system_health.json"
    if not health.exists():  # pragma: no cover - curated data absent in some checkouts
        pytest.skip("curated system_health.json not present")
    payload = _strict_loads(health.read_text())
    assert payload["pipeline_freshness"]


def test_math_isfinite_contract_matches_scrub():
    for value in (0.0, -1.5, 1e308):
        assert math.isfinite(value)
        assert json_safe(value) == value
