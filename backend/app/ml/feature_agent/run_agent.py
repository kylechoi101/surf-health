"""
Meta-learning feature-discovery agent for surf_health beach water quality.

Architecture (adapted from ~/Desktop/playground/src/run_agent.py):
  IDEATOR  → proposes a hypothesis (English)
  CODER    → writes a pandas function implementing it
  CRITIC   → static review of the code
  AST GATE → validator.py domain checks
  EXEC     → runs function in-memory, checks shape / no-row-explosion
  UNI GATE → univariate AUCPR > _UNIVARIATE_MIN_AUCPR
  CV GATE  → stratified-k-fold hist_gbm AUCPR ≥ baseline
  PERSIST  → appends winner to agent_features.py

Usage:
  cd backend
  python -m app.ml.feature_agent.run_agent [--iterations 50] [--curated PATH]

Requirements: Ollama running locally with gemma3:27b pulled.
"""
from __future__ import annotations

import ast
import datetime
import json
import os
import re
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score
from sklearn.model_selection import StratifiedKFold

# ── project imports ──────────────────────────────────────────────────────────
_BACKEND = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from app.data.pipeline.features import add_temporal_features, _model_feature_columns
from app.ml.feature_agent.validator import validate as ast_validate

# ── constants ────────────────────────────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3:27b"  # same model for all roles — avoids VRAM swapping

_UNIVARIATE_MIN_AUCPR = 0.15   # must beat this alone at base-rate 0.11
_CV_FOLDS = 3
_MAX_ITER_FILES = 100
_EXEC_TIMEOUT_S = 45.0

_LOGS_DIR = Path(__file__).parent / "agent_logs"
_KB_FILE = _LOGS_DIR / "knowledge_base.md"
_AGENT_FEATURES_FILE = Path(__file__).parent / "agent_features.py"

_BASELINE_AUCPR: float = 0.327   # hist_gbm_valid post-b7c8254 — update if retrained
_BASELINE_BRIER: float = 0.097

_SCHEMA_BLOCK = """
BEACH DATA SCHEMA
beach_day_df columns (one row per actual beach sample):
  beach_id          : str — unique station identifier
  sample_date       : datetime64 — date of the enterococcus measurement
  exceeds_stv       : bool — True if enterococcus > 104 CFU/100mL (the target)
  enterococcus_value: float — CFU/100mL (NaN if not yet sampled)
  wave_height_m     : float — significant wave height from nearest CDIP buoy (NaN if no buoy)
  dominant_period_s : float — wave period (s)
  salinity_psu      : float — sea-surface salinity (PSU)
  water_temperature_c: float — SST (°C)
  streamflow_cfs_latest / _mean_24h / _max_24h: float — USGS streamflow
  streamflow_rising_flag: float — 1 if streamflow increasing
  precip_mm_6h / _24h / _48h / _72h / _7d: float — precipitation totals
  precip_awi        : float — antecedent wetness index
  first_flush_flag  : float — 1 if this is the first rain after a dry spell
  advisory_active_prev_14d: int — 1 if any DPH advisory was active in last 14 days
  days_since_advisory_closed: float — days since last advisory ended (NaN if still open)
  historical_advisory_count: int — lifetime count of advisories at this station
  county            : str — e.g. "Los Angeles"
  region            : str — e.g. "Southern California"
  latitude / longitude: float
  cdip_distance_km  : float — km to nearest CDIP wave buoy
  erddap_distance_km: float — km to nearest ERDDAP SST/salinity sensor
  distance_to_pour_point_km / distance_to_gage_km: float — hydrology distances
  tidal_height / surf_height_observed / turbidity_observed: float (sparse)

advisories_df columns:
  beach_id, started_at (datetime), ended_at (datetime or NaT), cause (str)

stations_df columns (one row per unique beach_id):
  beach_id, county, region, latitude, longitude,
  cdip_distance_km, erddap_distance_km, historical_advisory_count

IMPORTANT CONSTRAINTS:
- base exceedance rate ~11% (1 in 9 samples exceeds STV)
- beach monitoring is WEEKLY or MONTHLY — not daily; many consecutive days have NO row
- many beaches share the same CDIP wave buoy → near-identical wave features across a region
- enterococcus_value at minimum detection (2 CFU/100mL) for most clean samples
"""


# ── knowledge base ───────────────────────────────────────────────────────────

def _read_kb() -> str:
    if _KB_FILE.exists():
        return _KB_FILE.read_text(encoding="utf-8")
    return "No historical knowledge base established yet."


def _append_kb(text: str) -> None:
    _LOGS_DIR.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entries = []
    if _KB_FILE.exists():
        entries = [e.strip() for e in _KB_FILE.read_text(encoding="utf-8").split("---\n") if e.strip()]
    entries.append(f"## Meta-Analysis: {ts}\n{text}".strip())
    _KB_FILE.write_text("\n".join(f"\n{e}\n---\n" for e in entries[-20:]), encoding="utf-8")


# ── iteration logs ───────────────────────────────────────────────────────────

def _write_iter(iteration: int, idea: str, code: str | None, errors: str, status: str, metric_info: str = "") -> None:
    _LOGS_DIR.mkdir(exist_ok=True)
    path = _LOGS_DIR / f"iteration_{iteration:04d}.md"
    lines = [
        f"# Iteration {iteration}\n",
        f"**Status:** {status}\n",
    ]
    if metric_info:
        lines.append(f"**Metrics:** {metric_info}\n")
    lines += ["\n---\n## Idea\n", idea, "\n---\n## Code\n"]
    if code:
        lines.append(f"```python\n{code}\n```\n")
    else:
        lines.append("*No code generated.*\n")
    if errors:
        lines += ["\n---\n## Errors\n", f"```\n{errors}\n```\n"]
    path.write_text("".join(lines), encoding="utf-8")


def _cleanup_logs() -> None:
    files = sorted(_LOGS_DIR.glob("iteration_*.md"), key=lambda p: p.stat().st_mtime)
    for old in files[:-_MAX_ITER_FILES]:
        old.unlink(missing_ok=True)


def _start_iteration() -> int:
    if not _LOGS_DIR.exists():
        return 1
    nums = [int(f.stem.split("_")[-1]) for f in _LOGS_DIR.glob("iteration_*.md") if f.stem.split("_")[-1].isdigit()]
    return max(nums) + 1 if nums else 1


def _existing_feature_names() -> list[str]:
    if not _AGENT_FEATURES_FILE.exists():
        return []
    try:
        tree = ast.parse(_AGENT_FEATURES_FILE.read_text(encoding="utf-8"))
        return [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("build_novel_feature_")]
    except Exception:
        return []


# ── Ollama ───────────────────────────────────────────────────────────────────

def _call_ollama(prompt: str, temperature: float = 0.7, max_tokens: int | None = None, max_retries: int = 3) -> str:
    options: dict = {"temperature": temperature, "seed": 42}
    if max_tokens:
        options["num_predict"] = max_tokens
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "options": options}
    for attempt in range(max_retries):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=300)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            raw = data.get("response", "")
            # strip <think>...</think> blocks (qwen3 / gemma reasoning traces)
            return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        except requests.Timeout:
            print(f"  [Ollama] timeout attempt {attempt+1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(5)
        except Exception as exc:
            print(f"  [Ollama] error attempt {attempt+1}/{max_retries}: {exc}")
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 5)
    raise RuntimeError(f"Ollama unreachable after {max_retries} retries")


def _check_ollama() -> None:
    try:
        requests.get(OLLAMA_URL.replace("/api/generate", "/"), timeout=5)
    except requests.ConnectionError:
        raise RuntimeError("Ollama not responding. Start it with: ollama serve")


# ── LLM roles ────────────────────────────────────────────────────────────────

def _ideate(existing_features: str, failed_history: str, kb: str, iteration: int) -> str | None:
    seed_ideas = """
SEED IDEA BANK (these are GOOD starting directions — explore variations):
- precip × wave_height interaction: rain + swell together mobilize fecal bacteria
- days_since_last_rain: first-flush window (highest risk in first 24h after dry spell)
- CDIP-buoy-relative wave anomaly: current wave vs 30D mean for THAT buoy
- county-level 7D exceedance rate: peer-beach pollution signal
- streamflow surge ratio: latest / 30D baseline (flash-flood risk)
- season × county: LA-county summer heat vs SF-county winter runoff
- historical_advisory_count_log1p per region: chronic-pollution zones
"""
    prompt = f"""You are a marine-biology and hydrology expert brainstorming predictive features for a beach water quality model.

{_SCHEMA_BLOCK}

LESSONS FROM PAST FAILURES:
{kb[:500]}

EXISTING FEATURES ALREADY IN THE MODEL (do not replicate these):
{existing_features[:400]}

PAST FAILED ATTEMPTS THIS SESSION:
{failed_history[:300] if failed_history else "(none yet)"}

{seed_ideas}

Propose ONE novel numeric feature. Rules:
- Must be computable from beach_day_df, advisories_df, or stations_df alone
- Must use per-beach or per-(beach, time-window) aggregations — no global stats
- Must be computable without leaking future data (no sample at date T can see data after T)
- No credit-risk concepts; this is ocean/hydrology/microbiology domain

Reply in EXACTLY this format (no Python code):
FEATURE NAME: [snake_case_name]
HYPOTHESIS: [one sentence why this predicts enterococcus exceedance]
IMPLEMENTATION: [3–5 bullet points describing the pandas operations, referencing exact column names]
"""
    try:
        return _call_ollama(prompt, temperature=0.9, max_tokens=400)
    except Exception as exc:
        print(f"  [Ideator] error: {exc}")
        return None


def _code(idea: str, existing_col_names: str, error_feedback: str = "", attempt: int = 0) -> str | None:
    error_section = f"\nPREVIOUS ATTEMPT FAILED — fix this error:\n{error_feedback[:500]}\n" if error_feedback else ""
    prompt = f"""Write a Python function that engineers a novel beach water-quality feature.

SPEC:
{idea[:800]}

{_SCHEMA_BLOCK}

{error_section}
RULES:
- Function signature EXACTLY: def build_novel_feature(beach_day_df, advisories_df, stations_df, **kwargs):
- Return a DataFrame with columns: beach_id, sample_date, <one_new_feature_column>
- Do NOT include exceeds_stv or enterococcus_value in the output
- ALL groupby on beach_day_df MUST be groupby('beach_id') — never global aggregations
- .shift() or .diff() MUST chain directly off .groupby('beach_id') to avoid cross-beach leakage
- .rolling() MUST use closed='left' (never include the current sample in its own window)
- After .groupby().agg(), call .reset_index() before accessing columns
- No for/while loops. No .apply(). No lambda inside .agg()
- Add 1e-9 to denominators. Use np.log1p() not np.log()
- sample_date MUST be preserved as datetime in the output
- Avoid column names already in use: {existing_col_names[:200]}

Output ONLY a ```python code block with the complete function including imports.
"""
    try:
        raw = _call_ollama(prompt, temperature=0.15, max_tokens=900)
        match = re.search(r"```python(.*?)```", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        match = re.search(r"```(.*?)```", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        # fallback: everything after "def build_novel_feature"
        idx = raw.find("def build_novel_feature")
        return raw[idx:].strip() if idx >= 0 else raw.strip()
    except Exception as exc:
        print(f"  [Coder] error: {exc}")
        return None


def _critic(code: str, error_feedback: str = "") -> tuple[bool, str]:
    error_ctx = f"\nPREVIOUS ERROR: {error_feedback}\nVerify the fix is present.\n" if error_feedback else ""
    prompt = f"""Review this beach water-quality feature engineering function for correctness.

```python
{code}
```
{error_ctx}
CHECKLIST:
1. Signature exactly `def build_novel_feature(beach_day_df, advisories_df, stations_df, **kwargs):`?
2. Returns DataFrame with beach_id, sample_date, and exactly ONE new numeric column?
3. .shift()/.diff() chains off .groupby('beach_id')? (prevents cross-beach leakage)
4. Any .rolling() uses closed='left'? (prevents current-sample leakage)
5. No for/while loops or .apply()? (performance)
6. No lambda inside .agg()? (performance)
7. Denominators guarded against zero division?
8. Does NOT output exceeds_stv or enterococcus_value columns?

Reply with exactly "PASS" if all checks pass, or "FAIL: <brief one-sentence reason>" if any check fails.
"""
    try:
        raw = _call_ollama(prompt, temperature=0.1, max_tokens=80)
        clean = raw.strip()
        if clean.upper().startswith("PASS"):
            return True, "PASS"
        return False, clean.replace("FAIL:", "").replace("FAIL", "").strip()
    except Exception as exc:
        print(f"  [Critic] error: {exc}")
        return True, "PASS (critic unavailable)"


def _analyze_failures(failed_logs: list[str]) -> str:
    log_text = "\n---\n".join(failed_logs[-8:])
    prompt = f"""You are a senior oceanography and ML engineer reviewing failed beach water-quality features.

Failed attempts:
{log_text}

{_SCHEMA_BLOCK}

Identify: (1) common mathematical traps, (2) domain misunderstandings, (3) THREE new orthogonal directions.
Keep it brief and technical. Use Markdown headings.
"""
    try:
        return _call_ollama(prompt, temperature=0.6, max_tokens=500)
    except Exception as exc:
        return f"(analysis failed: {exc})"


# ── execution ─────────────────────────────────────────────────────────────────

class _TimeoutError(Exception):
    pass


def _run_with_timeout(fn, timeout_s: float):
    result_box: list = [None]
    exc_box: list = [None]

    def target():
        try:
            result_box[0] = fn()
        except Exception as exc:
            exc_box[0] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        raise _TimeoutError(f"Timed out after {timeout_s}s")
    if exc_box[0]:
        raise exc_box[0]
    return result_box[0]


def _exec_feature(code: str, iteration: int, beach_day_sample: pd.DataFrame,
                  advisories_df: pd.DataFrame, stations_df: pd.DataFrame) -> tuple[pd.DataFrame | None, str]:
    # Rename function to avoid collision across iterations
    renamed = re.sub(r"def\s+build_novel_feature\s*\(", f"def build_novel_feature_{iteration}(", code, count=1)
    func_name = f"build_novel_feature_{iteration}"

    scope: dict = {"pd": pd, "np": np}
    try:
        exec(renamed, scope)  # noqa: S102
    except Exception as exc:
        return None, f"Compile error: {exc}"

    if func_name not in scope:
        return None, f"Function {func_name} not found after exec."

    fn = scope[func_name]

    try:
        result = _run_with_timeout(
            lambda: fn(beach_day_df=beach_day_sample, advisories_df=advisories_df, stations_df=stations_df),
            _EXEC_TIMEOUT_S,
        )
    except _TimeoutError as exc:
        return None, str(exc) + " — check for hidden loops or non-vectorized operations."
    except Exception as exc:
        return None, f"Runtime error: {traceback.format_exc()[-600:]}"

    # Shape checks
    if not isinstance(result, pd.DataFrame):
        return None, f"Function returned {type(result).__name__}, expected DataFrame."
    required = {"beach_id", "sample_date"}
    missing = required - set(result.columns)
    if missing:
        return None, f"Output missing required columns: {missing}."
    new_cols = [c for c in result.columns if c not in ("beach_id", "sample_date")]
    if len(new_cols) == 0:
        return None, "Output has no new feature column (only beach_id and sample_date)."
    if len(new_cols) > 1:
        return None, f"Output has {len(new_cols)} new columns; must return exactly ONE: {new_cols}."
    feat_col = new_cols[0]
    if " " in feat_col:
        return None, f"Feature column name '{feat_col}' contains spaces. Use underscores."
    forbidden_output = {"exceeds_stv", "enterococcus_value"}
    if forbidden_output & set(result.columns):
        return None, f"Output must not include {forbidden_output & set(result.columns)}."
    if result.duplicated(subset=["beach_id", "sample_date"]).any():
        return None, "Output has duplicate (beach_id, sample_date) rows — row explosion detected."
    return result, "ok"


# ── gates ──────────────────────────────────────────────────────────────────────

def _univariate_aucpr(features_with_feat: pd.DataFrame, feat_col: str) -> float:
    labeled = features_with_feat[["exceeds_stv", feat_col]].dropna()
    labeled = labeled.replace([np.inf, -np.inf], np.nan).dropna()
    if len(labeled) < 50 or labeled[feat_col].nunique() < 2:
        return 0.0
    try:
        return float(average_precision_score(labeled["exceeds_stv"].astype(int), labeled[feat_col]))
    except Exception:
        return 0.0


def _cv_aucpr(features_df: pd.DataFrame, feat_col: str, baseline_aucpr: float, seed: int = 42) -> float:
    """
    Stratified 3-fold CV with HistGradientBoostingClassifier.
    Returns mean AUCPR across folds using ALL current features + the new one.
    """
    feature_cols = [c for c in features_df.columns
                    if c not in {"beach_id", "sample_date", "exceeds_stv"}
                    and features_df[c].dtype.kind in "fi"]
    if feat_col not in feature_cols:
        feature_cols.append(feat_col)

    labeled = features_df[feature_cols + ["exceeds_stv"]].replace([np.inf, -np.inf], np.nan)
    labeled = labeled.dropna(subset=["exceeds_stv"])
    X = labeled[feature_cols].fillna(0.0).to_numpy(dtype=np.float32)
    y = labeled["exceeds_stv"].astype(int).to_numpy()

    if len(y) < 100:
        return 0.0

    skf = StratifiedKFold(n_splits=_CV_FOLDS, shuffle=True, random_state=seed)
    aucprs = []
    for train_idx, val_idx in skf.split(X, y):
        clf = HistGradientBoostingClassifier(
            max_iter=200,
            max_depth=4,
            learning_rate=0.05,
            min_samples_leaf=30,
            random_state=seed,
        )
        clf.fit(X[train_idx], y[train_idx])
        probs = clf.predict_proba(X[val_idx])[:, 1]
        aucprs.append(float(average_precision_score(y[val_idx], probs)))
    return float(np.mean(aucprs))


# ── persist ────────────────────────────────────────────────────────────────────

def _persist(code: str, iteration: int) -> None:
    renamed = re.sub(r"def\s+build_novel_feature\s*\(", f"def build_novel_feature_{iteration}(", code, count=1)
    with _AGENT_FEATURES_FILE.open("a", encoding="utf-8") as fh:
        fh.write(f"\n\n{renamed}\nAGENT_BUILDERS.append(build_novel_feature_{iteration})\n")


# ── main loop ──────────────────────────────────────────────────────────────────

def _load_data(curated_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    beach_day = pd.read_parquet(curated_dir / "beach_day.parquet")
    beach_day["sample_date"] = pd.to_datetime(beach_day["sample_date"])
    advisories = pd.read_parquet(curated_dir / "advisories.parquet")
    stations = pd.read_parquet(curated_dir / "beaches.parquet")
    return beach_day, advisories, stations


def _build_base_features(beach_day: pd.DataFrame) -> pd.DataFrame:
    """Compute the current model's feature set on all labeled rows."""
    labeled = beach_day[beach_day["exceeds_stv"].notna()].copy()
    enriched = add_temporal_features(labeled)
    feat_cols = _model_feature_columns(enriched)
    result = enriched[feat_cols + ["beach_id", "sample_date", "exceeds_stv"]].copy()
    return result


def run_loop(max_iterations: int = 50, curated_dir: Path | None = None) -> None:
    if curated_dir is None:
        curated_dir = Path(__file__).resolve().parents[4] / "data" / "curated"

    print("\n--- SURF HEALTH FEATURE-DISCOVERY AGENT ---")
    _check_ollama()
    print(f"✅ Ollama OK  |  model: {OLLAMA_MODEL}")
    print(f"   Curated: {curated_dir}")

    _LOGS_DIR.mkdir(exist_ok=True)

    print("\nLoading beach_day.parquet + advisories + stations...")
    beach_day, advisories, stations = _load_data(curated_dir)

    # Sample for fast exec tests (recent 2 years labeled data, up to 80K rows)
    two_years_ago = pd.Timestamp.now() - pd.DateOffset(years=2)
    exec_sample = beach_day[
        beach_day["exceeds_stv"].notna() & (beach_day["sample_date"] >= two_years_ago)
    ].copy()
    if len(exec_sample) > 80_000:
        exec_sample = exec_sample.sample(80_000, random_state=42)
    print(f"   Exec sample: {len(exec_sample):,} labeled rows  (base rate: {exec_sample['exceeds_stv'].mean():.2%})")

    print("\nBuilding base feature matrix (this takes ~60s)...")
    base_features = _build_base_features(beach_day)
    baseline_aucpr = _cv_aucpr(base_features, feat_col="__dummy__", baseline_aucpr=_BASELINE_AUCPR)
    print(f"   Baseline CV AUCPR (stratified 3-fold): {baseline_aucpr:.4f}")

    existing_fns = _existing_feature_names()
    print(f"   Existing agent features: {len(existing_fns)}")

    start = _start_iteration()
    failed_logs: list[str] = []
    current_features = base_features.copy()
    current_aucpr = baseline_aucpr

    for i in range(start, start + max_iterations):
        _cleanup_logs()
        print(f"\n{'='*55}")
        print(f"  ITERATION {i}  (baseline AUCPR {current_aucpr:.4f})")

        # ── meta-analysis after 4 consecutive failures ──
        is_meta = len(failed_logs) >= 4
        if is_meta:
            print("  🧠 Meta-analysis triggered on past failures...")
            analysis = _analyze_failures(failed_logs)
            _append_kb(analysis)
            history_str = f"META-ANALYSIS:\n{analysis}"
            failed_logs.clear()
        else:
            history_str = "\n---\n".join(failed_logs[-4:])

        # ── existing feature names for de-dup prompt ──
        all_cols = ", ".join(c for c in current_features.columns if c not in {"beach_id", "sample_date", "exceeds_stv"})
        fn_names = ", ".join(_existing_feature_names())

        # ── IDEATE ──
        idea = _ideate(existing_features=fn_names, failed_history=history_str, kb=_read_kb(), iteration=i)
        if not idea:
            print("  ⚠️  Ideator empty — skipping.")
            continue
        print(f"  💡 {idea[:120].splitlines()[0]}")

        # ── GENERATE + VALIDATE (up to 3 attempts) ──
        code: str | None = None
        result_df: pd.DataFrame | None = None
        error_feedback = ""

        for attempt in range(3):
            new_code = _code(idea, existing_col_names=all_cols, error_feedback=error_feedback, attempt=attempt)
            if not new_code:
                error_feedback = "No parseable code block returned."
                continue

            print(f"  [attempt {attempt+1}] AST validation...")
            ok, err = ast_validate(new_code)
            if not ok:
                error_feedback = f"AST FAILED: {err}"
                print(f"  [attempt {attempt+1}] ❌ AST: {err[:120]}")
                continue

            print(f"  [attempt {attempt+1}] Critic review...")
            passed, critic_fb = _critic(new_code, error_feedback=error_feedback)
            if not passed:
                error_feedback = f"CRITIC: {critic_fb}"
                print(f"  [attempt {attempt+1}] ❌ Critic: {critic_fb[:120]}")
                continue

            print(f"  [attempt {attempt+1}] Executing...")
            result_df, exec_msg = _exec_feature(new_code, i, exec_sample, advisories, stations)
            if result_df is None:
                error_feedback = f"EXEC: {exec_msg}"
                print(f"  [attempt {attempt+1}] ❌ Exec: {exec_msg[:120]}")
                continue

            code = new_code
            break

        if result_df is None or code is None:
            print(f"  ❌ ALL ATTEMPTS FAILED")
            failed_logs.append(f"Idea:\n{idea}\nFinal error: {error_feedback}")
            _write_iter(i, idea, code, error_feedback, "FAILED (code/exec)")
            continue

        feat_col = [c for c in result_df.columns if c not in ("beach_id", "sample_date")][0]
        print(f"  ✅ Exec OK  |  feature: {feat_col}")

        # ── join feature onto exec_sample for univariate gate ──
        merged_sample = exec_sample[["beach_id", "sample_date", "exceeds_stv"]].merge(
            result_df, on=["beach_id", "sample_date"], how="left"
        )
        uni = _univariate_aucpr(merged_sample, feat_col)
        print(f"  📊 Univariate AUCPR: {uni:.4f}  (need > {_UNIVARIATE_MIN_AUCPR})")
        if uni <= _UNIVARIATE_MIN_AUCPR:
            msg = f"Weak standalone signal (AUCPR {uni:.4f} ≤ {_UNIVARIATE_MIN_AUCPR})"
            failed_logs.append(f"Idea:\n{idea}\nResult: {msg}")
            _write_iter(i, idea, code, msg, "FAILED (univariate gate)")
            continue

        # ── join feature onto full base_features for CV gate ──
        # Join the new column into current_features
        full_result = beach_day[["beach_id", "sample_date", "exceeds_stv"]].merge(
            result_df, on=["beach_id", "sample_date"], how="left"
        )
        augmented = current_features.merge(
            full_result[["beach_id", "sample_date", feat_col]],
            on=["beach_id", "sample_date"], how="left"
        )

        # Correlation guard (< 0.85 with any existing numeric col)
        numeric_existing = [c for c in current_features.columns
                            if c not in {"beach_id", "sample_date", "exceeds_stv"}
                            and current_features[c].dtype.kind in "fi"]
        if numeric_existing:
            max_corr = augmented[numeric_existing].corrwith(augmented[feat_col]).abs().max()
            if max_corr > 0.85:
                msg = f"High correlation ({max_corr:.2f}) with existing features — redundant."
                failed_logs.append(f"Idea:\n{idea}\nResult: {msg}")
                _write_iter(i, idea, code, msg, "FAILED (correlation gate)")
                continue
            print(f"  📐 Max correlation with existing features: {max_corr:.3f}")

        print(f"  🔄 Running {_CV_FOLDS}-fold CV (stratified)...")
        new_aucpr = _cv_aucpr(augmented, feat_col, baseline_aucpr=current_aucpr)
        delta = new_aucpr - current_aucpr
        print(f"  📈 CV AUCPR: {current_aucpr:.4f} → {new_aucpr:.4f}  ({delta:+.4f})")

        if new_aucpr < current_aucpr:
            msg = f"Degrades CV AUCPR ({current_aucpr:.4f} → {new_aucpr:.4f})"
            failed_logs.append(f"Idea:\n{idea}\nResult: {msg}")
            _write_iter(i, idea, code, msg, "FAILED (CV gate)", f"Uni: {uni:.4f} | CV: {new_aucpr:.4f}")
            continue

        # ── ACCEPT ──
        print(f"  🎉 ACCEPTED: {feat_col}")
        _persist(code, i)
        current_features = augmented.copy()
        current_aucpr = new_aucpr
        _write_iter(i, idea, code, "", "SUCCESS", f"Uni: {uni:.4f} | CV: {new_aucpr:.4f} (+{delta:.4f})")
        failed_logs.clear()

    print(f"\n--- Done. Final CV AUCPR: {current_aucpr:.4f} (started {baseline_aucpr:.4f}) ---")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Surf Health feature-discovery agent")
    ap.add_argument("--iterations", type=int, default=50)
    ap.add_argument("--curated", type=Path, default=None, help="Path to data/curated/")
    args = ap.parse_args()
    run_loop(max_iterations=args.iterations, curated_dir=args.curated)
