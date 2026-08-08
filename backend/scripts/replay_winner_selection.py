#!/usr/bin/env python
"""Replay the production-winner selection over recovered historical backtest metrics.

This is the exit-criterion harness for step 9 of the rebuild programme: the
winner-tenure change must produce <=2 winner changes over the last 105 days
instead of the 11 that actually happened, *without* locking out a genuinely
better model.

**What the input is, and what it is not.** There is no recorded log of "what the
gate decided each run". The replay reconstructs one:

* Per-run candidate metrics come from ``data/curated/system_health.json`` at every
  commit that touched it (226 commits; 225 parse, 1 is an empty blob). The
  ``model_registry.spatial_metrics`` block carries held-out county and beach
  AUCPR / Brier / calibration slope for **every** backtested candidate, which is
  exactly the dict :func:`_spatially_qualified_production_winner` consumes. Note
  that ``production_metrics`` / ``validation_metrics`` are FLAT metric dicts for
  the winner, not per-model, and must not be merged in.
* The paired cluster bootstrap needs per-row holdout predictions.
  ``holdout_predictions_spatial.parquet`` has been committed only since
  **2026-06-11** (69 commits), so it is available for ~37% of replayed runs. On
  the rest the replay lands on the gate's own no-evidence branch
  (``_WINNER_SWAP_LARGE_GAP_MARGIN``). That is a real limitation and it is
  concentrated in exactly the April-June churn period, so the "current rule" arm
  is an approximation there, not a reconstruction.
* ``spatial_backtest_models`` in the payload stores model *version* strings
  ("hist-gbm-curated-v0"); the selector keys on internal names. The candidate set
  is therefore derived from the ``spatial_county_*`` keys actually present.

**This is a counterfactual, not history.** It asks "what would today's selector,
with and without the tenure layer, have done given this metric stream" — not
"what happened". What happened was also driven by older selection code, by manual
``production_model.json`` promotions, and by the fact that the daily gate never
persisted its own decision.

Usage::

    python scripts/replay_winner_selection.py                # build + replay
    python scripts/replay_winner_selection.py --corpus /tmp/c.json --sweep
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ml.training import (  # noqa: E402
    _WINNER_EMERGENCY_CONFIRMATION_RUNS,
    _WINNER_MIN_TENURE_DAYS,
    _WINNER_SWAP_CONFIRMATION_RUNS,
    WinnerTenure,
    _apply_winner_tenure,
    _promotion_assessment,
    _spatially_qualified_production_winner,
)

REPO = Path(__file__).resolve().parents[2]
HEALTH = "data/curated/system_health.json"
HOLDOUT = "data/curated/holdout_predictions_spatial.parquet"
# hist_gbm, _persistence_blend and _positive_persistence_guard are ONE trained
# HistGBM fit wearing three inference-time wrappers. A change between them cannot
# be a modelling improvement, whatever the backtest says.
SAME_CLASSIFIER = {
    "hist-gbm-curated-v0",
    "hist-gbm-persistence-blend-curated-v0",
    "hist-gbm-positive-persistence-guard-curated-v0",
}


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, cwd=REPO)


def _git_text(*args: str) -> str:
    return _git(*args).stdout.decode("utf-8", "replace")


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------


def build_corpus() -> dict:
    log = _git_text("log", "--format=%H|%ad", "--date=iso-strict", "--", HEALTH)
    lines = [ln for ln in log.strip().split("\n") if ln]
    runs, unrecoverable = [], []
    for line in reversed(lines):  # chronological
        sha, ts = line.split("|")
        blob = _git_text("show", f"{sha}:{HEALTH}")
        try:
            payload = json.loads(blob)
        except Exception as exc:  # noqa: BLE001 - report, never abort the replay
            unrecoverable.append({"sha": sha, "ts": ts, "bytes": len(blob),
                                  "reason": str(exc)[:80]})
            continue
        registry = payload.get("model_registry") or {}
        merged: dict = {}
        for key in ("metrics", "spatial_metrics"):
            block = registry.get(key)
            if isinstance(block, dict):
                for name, value in block.items():
                    if isinstance(value, dict):
                        merged.setdefault(name, value)
        runs.append({
            "sha": sha,
            "ts": ts,
            "production_model": registry.get("production_model"),
            "metrics": merged,
        })
    return {"runs": runs, "unrecoverable": unrecoverable}


_SINK_CACHE: dict[str, dict | None] = {}


def sink_for(sha: str) -> dict | None:
    """The gate's ``predictions_sink``, reconstructed from the committed spatial
    holdout predictions at this sha. ``None`` when the artifact predates the
    commit that started persisting it (2026-06-11)."""
    if sha not in _SINK_CACHE:
        blob = _git("show", f"{sha}:{HOLDOUT}")
        if blob.returncode != 0 or not blob.stdout:
            _SINK_CACHE[sha] = None
        else:
            frame = pd.read_parquet(io.BytesIO(blob.stdout))
            _SINK_CACHE[sha] = {
                (model, kind): {
                    "labels": grp["label"].to_numpy(),
                    "probabilities": grp["probability"].to_numpy(dtype=float),
                    "groups": grp["group"].to_numpy(),
                }
                for (model, kind), grp in frame.groupby(["model", "holdout_kind"])
            }
    return _SINK_CACHE[sha]


def candidates_for(run: dict) -> tuple[str, ...]:
    return tuple(sorted(
        key[len("spatial_county_"):]
        for key in run["metrics"]
        if key.startswith("spatial_county_") and key != "spatial_county_persistence"
    ))


def model_key(version: str | None) -> str | None:
    if not version:
        return None
    key = version.split("+")[0]
    if key.endswith("-curated-v0"):
        key = key[: -len("-curated-v0")]
    key = key.replace("-", "_")
    return {"logistic_global": "logistic",
            "logistic_county": "logistic_hierarchical",
            "logistic_region": "logistic_hierarchical"}.get(key, key)


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------


_CHOICE_CACHE: dict[tuple, str] = {}


def statistical_choice(run: dict, incumbent: str, cands: tuple[str, ...]) -> str:
    """Today's selector's verdict on this run alone. Memoized: the paired cluster
    bootstrap dominates the runtime and depends only on (run, incumbent)."""
    cache_key = (run["sha"], incumbent, cands)
    if cache_key not in _CHOICE_CACHE:
        _CHOICE_CACHE[cache_key] = _spatially_qualified_production_winner(
            run["metrics"], preferred=incumbent, candidates=cands,
            predictions_sink=sink_for(run["sha"]),
        )
    return _CHOICE_CACHE[cache_key]


def replay(runs: list[dict], *, start: str, tenure_days: int | None,
           confirm_runs: int = 1, emergency_runs: int = 1) -> dict:
    """``tenure_days=None`` replays the current rule (statistical tests only)."""
    incumbent, tenure = start, WinnerTenure(winner=start, promoted_at=None)
    swaps, suppressed, evaluated, with_sink = [], [], 0, 0
    for run in runs:
        cands = candidates_for(run)
        if not cands:
            continue
        if incumbent not in cands:
            cands = (incumbent, *cands)
        evaluated += 1
        with_sink += bool(sink_for(run["sha"]))
        now = datetime.fromisoformat(run["ts"])
        if tenure is not None and tenure.promoted_at is None:
            tenure = WinnerTenure(winner=incumbent, promoted_at=now)
        choice = statistical_choice(run, incumbent, cands)
        if tenure_days is None:
            final, record = choice, {}
        else:
            final, tenure, record = _apply_winner_tenure(
                incumbent=incumbent,
                statistical_choice=choice,
                tenure=tenure,
                now=now,
                incumbent_passing=bool(
                    _promotion_assessment(run["metrics"], incumbent)["public_release_eligible"]
                ),
                min_tenure_days=tenure_days,
                confirmation_runs=confirm_runs,
                emergency_confirmation_runs=emergency_runs,
            )
        if record.get("suppressed_swap"):
            suppressed.append({"ts": run["ts"], **record})
        if final != incumbent:
            swaps.append({"ts": run["ts"], "from": incumbent, "to": final,
                          "reason": record.get("swap_reason", "statistical")})
            incumbent = final
    return {"swaps": swaps, "suppressed": suppressed,
            "evaluated": evaluated, "with_sink": with_sink}


# --------------------------------------------------------------------------
# Ground truth: what the product actually served
# --------------------------------------------------------------------------


def historical_changes() -> list[tuple[str, str, str]]:
    """Served-winner changes at DAILY resolution from forecast_history.parquet —
    the last run of each forecast date, which is what shipped."""
    frame = pd.read_parquet(REPO / "data/curated/forecast_history.parquet")
    frame["fg"] = pd.to_datetime(frame["forecast_generated_at"], utc=True, errors="coerce")
    frame["fd"] = pd.to_datetime(frame["forecast_date"])
    newest = frame.groupby("fd")["fg"].max()
    last = frame.merge(newest.rename("maxfg"), left_on="fd", right_index=True)
    last = last[last["fg"] == last["maxfg"]]
    per_day = (
        last.groupby("fd")["model_version"]
        .agg(lambda s: "+".join(sorted(s.unique())))
        .sort_index()
    )
    changes, prev = [], None
    for day, version in per_day.items():
        if version != prev:
            if prev is not None:
                changes.append((day.date().isoformat(), prev, version))
            prev = version
    return changes


def registry_promotions() -> dict[str, str]:
    """Dates on which production_model.json actually changed — i.e. the winner
    changes that were DELIBERATE rather than an ephemeral daily-gate swap."""
    out = {}
    log = _git_text("log", "--format=%H|%ad", "--date=short", "--",
                    "data/curated/production_model.json")
    for line in [ln for ln in log.strip().split("\n") if ln]:
        sha, day = line.split("|")
        out[day] = json.loads(_git_text("show", f"{sha}:data/curated/production_model.json"))["winner"]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=None,
                        help="cache the recovered corpus here (rebuilt if absent)")
    parser.add_argument("--sweep", action="store_true",
                        help="also sweep tenure / confirmation / emergency parameters")
    args = parser.parse_args(argv)

    if args.corpus and args.corpus.exists():
        data = json.loads(args.corpus.read_text())
    else:
        data = build_corpus()
        if args.corpus:
            args.corpus.write_text(json.dumps(data))

    runs = [r for r in data["runs"] if any(k.startswith("spatial_county_") for k in r["metrics"])]

    print("=" * 78)
    print("INPUT — what could and could not be recovered")
    print("=" * 78)
    print(f"  health snapshots in git history      : {len(data['runs']) + len(data['unrecoverable'])}")
    print(f"  ... parsed                           : {len(data['runs'])}")
    print(f"  ... carrying spatial backtest metrics: {len(runs)}   <- the replay stream")
    for bad in data["unrecoverable"]:
        print(f"  ... UNRECOVERABLE {bad['sha'][:12]} {bad['ts'][:10]} "
              f"({bad['bytes']} bytes): {bad['reason']}")
    print(f"  span: {runs[0]['ts'][:10]} -> {runs[-1]['ts'][:10]}")

    changes = historical_changes()
    promotions = registry_promotions()
    print()
    print("=" * 78)
    print(f"GROUND TRUTH — {len(changes)} served-winner changes (forecast_history, daily resolution)")
    print("=" * 78)
    n_persisted = n_wrapper = 0
    for day, frm, to in changes:
        persisted = day in promotions
        wrapper = frm.split("+")[0] in SAME_CLASSIFIER and to.split("+")[0] in SAME_CLASSIFIER
        n_persisted += persisted
        n_wrapper += wrapper
        tag = ("DELIBERATE (registry commit)" if persisted else "ephemeral daily-gate swap")
        if wrapper:
            tag += " | SAME trained classifier, wrapper only"
        print(f"  {day}  {frm.split('+')[0]:<46} -> {to.split('+')[0]}")
        print(f"              {tag}")
    print()
    print(f"  reached production_model.json      : {n_persisted}/{len(changes)}")
    print(f"  same trained fit, post-processing  : {n_wrapper}/{len(changes)}")

    start = model_key(runs[0]["production_model"]) or candidates_for(runs[0])[0]
    print()
    print("=" * 78)
    print(f"ARM A — current rule, incumbent carried forward (start={start})")
    print("=" * 78)
    arm_a = replay(runs, start=start, tenure_days=None)
    for swap in arm_a["swaps"]:
        print(f"  {swap['ts'][:10]}  {swap['from']} -> {swap['to']}")
    print(f"  runs evaluated {arm_a['evaluated']}   SWAPS {len(arm_a['swaps'])}")
    print(f"  paired bootstrap available on {arm_a['with_sink']}/{arm_a['evaluated']} runs "
          f"({arm_a['with_sink'] / arm_a['evaluated']:.0%}); the rest use the 0.07 no-evidence rule")

    if args.sweep:
        print()
        print("=" * 78)
        print("PARAMETER SWEEP")
        print("=" * 78)
        for tenure_days, confirm, emergency in (
            (60, 7, 1), (60, 7, 2), (60, 7, 3), (60, 7, 4),
            (60, 5, 3), (60, 3, 3), (60, 1, 3),
            (90, 7, 3), (45, 7, 3), (30, 7, 3), (14, 7, 3),
        ):
            out = replay(runs, start=start, tenure_days=tenure_days,
                         confirm_runs=confirm, emergency_runs=emergency)
            print(f"  tenure={tenure_days:>2}d confirm={confirm} emergency={emergency} "
                  f"-> swaps={len(out['swaps'])} suppressed_runs={len(out['suppressed'])}")

    print()
    print("=" * 78)
    print("ARM B — SHIPPED configuration (constants read from app.ml.training)")
    print("=" * 78)
    print(f"  _WINNER_MIN_TENURE_DAYS            = {_WINNER_MIN_TENURE_DAYS}")
    print(f"  _WINNER_SWAP_CONFIRMATION_RUNS     = {_WINNER_SWAP_CONFIRMATION_RUNS}")
    print(f"  _WINNER_EMERGENCY_CONFIRMATION_RUNS = {_WINNER_EMERGENCY_CONFIRMATION_RUNS}")
    arm_b = replay(runs, start=start, tenure_days=_WINNER_MIN_TENURE_DAYS,
                   confirm_runs=_WINNER_SWAP_CONFIRMATION_RUNS,
                   emergency_runs=_WINNER_EMERGENCY_CONFIRMATION_RUNS)
    for swap in arm_b["swaps"]:
        print(f"  {swap['ts'][:10]}  {swap['from']} -> {swap['to']}  [{swap['reason']}]")
    print(f"  SWAPS {len(arm_b['swaps'])}  (historical {len(changes)}, current rule {len(arm_a['swaps'])})")
    print(f"  runs on which a swap was suppressed: {len(arm_b['suppressed'])}")
    breakdown = collections.Counter(
        (s.get("winner"), s.get("challenger")) for s in arm_b["suppressed"]
    )
    for (winner, challenger), count in breakdown.most_common():
        print(f"      {count:>3} runs   held {winner} over {challenger}")

    ok = len(arm_b["swaps"]) <= 2
    print()
    print(f"EXIT CRITERION (<=2 swaps over the window): {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
