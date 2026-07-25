"""Strict JSON serialization for everything the pipeline publishes.

Python's ``json.dumps`` writes ``NaN`` / ``Infinity`` for non-finite floats by
default. Those tokens are NOT valid JSON (RFC 8259), so every non-Python
consumer rejects the whole document:

  * ``JSON.parse`` throws ``SyntaxError: Unexpected token 'N'`` — this took down
    the shorelife-web static export on 2026-07-24, which prerenders /research
    from ``system_health.json`` and failed the build outright;
  * anything else that reads the file or the sqlite health row with a strict
    parser (jq, Go, Rust, a browser) rejects the whole document, not just the
    offending field.

The API happens to survive it: FastAPI's ``jsonable_encoder`` runs the response
model through pydantic v2's ``model_dump(mode="json")``, whose default
``ser_json_inf_nan="null"`` already maps non-finite floats to ``null`` before
Starlette's ``allow_nan=False`` renderer sees them (verified against the pinned
FastAPI: ``/system/health`` returned 200 while serving a NaN-carrying snapshot).
That is luck downstream of the bug, not a reason to publish invalid JSON.

A NaN metric is a legitimate result — an AUROC over a bucket where no beach
qualified is genuinely undefined (see ``two_tier.within_beach_auroc``). What is
not legitimate is publishing it as a bare ``NaN`` token. ``json_safe`` maps
non-finite floats to ``null``, which is what "undefined" means to a consumer,
and ``dumps_strict`` then serializes with ``allow_nan=False`` so any future
producer that slips a non-finite value past the scrub fails loudly at the write
instead of shipping a document nobody downstream can parse.
"""

from __future__ import annotations

import json
import math
from typing import Any

__all__ = ["json_safe", "dumps_strict", "write_json"]


def json_safe(value: Any) -> Any:
    """Recursively replace non-finite floats with ``None``.

    Also normalizes numpy scalars (``np.float64('nan')``, ``np.int64``) via
    ``.item()``, which the metrics payloads are full of — they serialize fine
    only because they subclass Python floats.
    """
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]

    # numpy scalars (and anything else exposing .item()) -> native Python.
    item = getattr(value, "item", None)
    if callable(item) and not isinstance(value, (str, bytes, dict, list, tuple)):
        try:
            value = item()
        except (TypeError, ValueError):  # pragma: no cover - defensive
            pass

    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def dumps_strict(payload: Any, *, indent: int | None = 2) -> str:
    """``json.dumps`` the payload as spec-compliant JSON.

    Scrubs non-finite floats to ``null`` first, then serializes with
    ``allow_nan=False`` so an unscrubbable value raises here rather than
    producing a document that only Python can read.
    """
    return json.dumps(json_safe(payload), indent=indent, allow_nan=False)


def write_json(path, payload: Any, *, indent: int | None = 2) -> None:
    """Write ``payload`` to ``path`` as spec-compliant JSON."""
    path.write_text(dumps_strict(payload, indent=indent))
