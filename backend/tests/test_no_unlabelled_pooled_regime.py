"""Guard: no served figure is published without its regime provenance (E5).

Sibling of ``test_no_unstratified_published_metric.py``, which guards the ASSAY
cut. This one guards the SERVING-REGIME cut, and the two compose: assay is
*which labelling universe scored the row*, regime is *which serving stack
produced it*. A number can be honest about one and silently wrong about the
other.

Two failure modes, one behavioural check and one structural:

1. **A new publication site ships a pooled figure unlabelled.** The published
   "how good is the product" number averaged eight ``model_version``s, most of
   them not running, and nothing in the payload said so.

2. **A provenance column is added to the schema but never populated.** This is
   not hypothetical: ``served_offset_weight`` entered ``_HISTORY_COLUMNS`` on
   2026-07-29, seven days after the two-tier router went live, so 2026-07-22..28
   is router-served and logged as pre-router — permanently unrecoverable. The
   reverse of that mistake (a column in the schema that no serve path writes)
   produces an all-null column that looks like data.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd

from app.ml.served_metrics import (
    _HISTORY_COLUMNS,
    append_forecast_history,
    served_performance,
)

TRAINING = Path(__file__).resolve().parents[1] / "app" / "ml" / "training.py"


def _forecast_row(beach, day, p, fingerprint=None):
    row = {
        "beach_id": beach,
        "forecast_date": day,
        "p_exceed": p,
        "p_exceed_raw": p,
        "p_exceed_precal": p,
        "risk_band": "Low" if p < 0.2 else "High",
        "sample_age_days": 5,
        "model_version": "test-v0",
        "forecast_generated_at": f"{day}T18:00:00+00:00",
    }
    if fingerprint is not None:
        row["serving_config_fingerprint"] = fingerprint
        row["persistence_floor_applied"] = False
    return row


def _payload_with_two_regimes(tmp_path) -> dict:
    rng = np.random.default_rng(23)
    rows, observations = [], []
    for era, (start, fingerprint) in enumerate(
        [("2026-06-01", None), ("2026-07-10", "livefp0000000000")]
    ):
        base = pd.Timestamp(start)
        for i in range(140):
            beach = f"e{era}b{i}"
            day = (base + pd.Timedelta(days=i % 20)).date().isoformat()
            p = float(np.clip(rng.random(), 0.02, 0.95))
            rows.append(_forecast_row(beach, day, p, fingerprint))
            observations.append((beach, day, bool(rng.random() < p)))
    pd.DataFrame(rows).to_parquet(tmp_path / "forecasts.parquet", index=False)
    append_forecast_history(tmp_path)
    pd.DataFrame(
        observations, columns=["beach_id", "sample_date", "exceeds_stv"]
    ).to_parquet(tmp_path / "observations.parquet", index=False)
    return served_performance(tmp_path, windows=(90,))


def _blocks_with_a_metric(node, path=("served_metrics",), under_regime=False):
    """Yield (path, block, under_regime) for every dict that publishes an AUCPR."""
    if isinstance(node, dict):
        if "aucpr" in node:
            yield path, node, under_regime
        for key, value in node.items():
            yield from _blocks_with_a_metric(
                value, path + (str(key),), under_regime or key == "by_regime"
            )
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _blocks_with_a_metric(value, path + (str(index),), under_regime)


def test_every_pooled_published_metric_declares_that_it_is_pooled(tmp_path) -> None:
    payload = _payload_with_two_regimes(tmp_path)
    violations = [
        "/".join(path)
        for path, block, under_regime in _blocks_with_a_metric(payload)
        if not under_regime and not block.get("pooled_across_regimes")
    ]
    assert not violations, (
        "these published figures pool across serving configurations without "
        "saying so — attach pooled_across_regimes + POOLED_REGIME_CAVEAT, or "
        "publish them under by_regime:\n  " + "\n  ".join(violations)
    )


def test_every_published_aucpr_carries_its_base_rate_caveat(tmp_path) -> None:
    """E4. AUCPR moves with the population mix at constant skill — Step 7's
    pooled 0.8168 concealed culture 0.3875 / ddPCR 0.9707, and the LIFT inverts
    the ranking. The caveat travels with the number, not in a header."""
    payload = _payload_with_two_regimes(tmp_path)
    missing = [
        "/".join(path)
        for path, block, _ in _blocks_with_a_metric(payload)
        if "aucpr_caveat" not in block
    ]
    assert not missing, "AUCPR published without its caveat:\n  " + "\n  ".join(missing)


def test_the_payload_actually_splits_by_regime(tmp_path) -> None:
    """The guards above are vacuous if nothing is ever stratified."""
    window = _payload_with_two_regimes(tmp_path)["window_90d"]
    assert "by_regime" in window
    assert "livefp0000000000" in window["by_regime"]
    assert any(key.startswith("legacy:") for key in window["by_regime"])


def _forecast_row_keys() -> set[str]:
    """String keys of the forecast-row dict literal built in `_export_forecasts`."""
    tree = ast.parse(TRAINING.read_text())
    export = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_export_forecasts"
    )
    keys: set[str] = set()
    for node in ast.walk(export):
        if isinstance(node, ast.Dict):
            keys.update(
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )
    return keys


def test_every_history_column_is_written_by_the_serve_path() -> None:
    """A column in ``_HISTORY_COLUMNS`` that ``_export_forecasts`` never emits is
    an all-null column that reads as data. ``append_forecast_history`` fills any
    missing column with None without complaint, so nothing else catches it."""
    unwritten = sorted(set(_HISTORY_COLUMNS) - _forecast_row_keys())
    assert not unwritten, (
        "these forecast-history columns are declared but never populated by "
        f"_export_forecasts: {unwritten}"
    )


def test_the_fingerprint_is_part_of_the_history_schema() -> None:
    assert "serving_config_fingerprint" in _HISTORY_COLUMNS
