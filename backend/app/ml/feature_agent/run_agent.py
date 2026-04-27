"""
Meta-learning feature-discovery agent for surf_health beach water quality.

Architecture:
  IDEATOR  → proposes a hypothesis (English)
  CODER    → writes a pandas function implementing it
  CRITIC   → static review of the code
  AST GATE → validator.py domain checks
  EXEC     → runs function in-memory, checks shape / no-row-explosion
  UNI GATE → univariate AUCPR > _UNIVARIATE_MIN_AUCPR
  CV GATE  → multi-seed county-grouped GroupKFold
             accept if bootstrap CI₁₀ of AUCPR > current baseline  (play #1+#2)
             OR  AUCPR doesn't regress AND Brier improves ≥ 0.0003  (play #3)
  PERSIST  → appends winner to agent_features.py

Usage:
  cd backend
  # Ollama (local)
  python -m app.ml.feature_agent.run_agent [--iterations 100] [--curated PATH]

  # NVIDIA NIM (fast, ~30s/iter)
  NVIDIA_API_KEYS="key1,key2" LLM_PROVIDER=nim \
    python -m app.ml.feature_agent.run_agent --iterations 100

  # env: LLM_PROVIDER=ollama (default) | nim
  #      FEATURE_AGENT_MODEL  — NIM model string, default minimaxai/minimax-m2.5
  #      NVIDIA_API_KEYS      — comma-separated API keys for round-robin
"""
from __future__ import annotations

import ast
import datetime
import itertools
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
from sklearn.metrics import average_precision_score, brier_score_loss
from sklearn.model_selection import GroupKFold

# ── project imports ──────────────────────────────────────────────────────────
_BACKEND = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from app.data.pipeline.features import add_temporal_features, _model_feature_columns
from app.ml.feature_agent.validator import validate as ast_validate

# ── constants ────────────────────────────────────────────────────────────────
_LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()  # "ollama" | "nim"

# Ollama settings
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = os.environ.get("FEATURE_AGENT_MODEL", "gemma3:27b")

# NVIDIA NIM settings
_NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_NIM_MODEL = os.environ.get("FEATURE_AGENT_MODEL", "meta/llama-3.3-70b-instruct")
_NIM_KEYS: list[str] = [k.strip() for k in os.environ.get("NVIDIA_API_KEYS", "").split(",") if k.strip()]
_nim_key_pool = itertools.cycle(_NIM_KEYS) if _NIM_KEYS else None
_current_nim_key: str | None = None  # pinned per-iteration; advanced in run_loop

_UNIVARIATE_MIN_AUCPR = 0.15   # must beat this alone at base-rate 0.11
_MIN_BRIER_DELTA = 0.0005      # Brier must not degrade by more than this (AUCPR gate)
_BRIER_ONLY_MIN_IMPROVEMENT = 0.0003  # Brier must improve by at least this (Brier-only lane)
_AUCPR_BRIER_ONLY_MAX_REGRESS = 0.001 # AUCPR may slip at most this much in Brier-only lane
_CV_FOLDS = 3
_CV_SEEDS = (42, 7, 13)  # multi-seed averaging: reduces HistGBM stochasticity noise
_MAX_ITER_FILES = 100
_EXEC_TIMEOUT_S = 45.0

_LOGS_DIR = Path(__file__).parent / "agent_logs"
_KB_FILE = _LOGS_DIR / "knowledge_base.md"
_AGENT_FEATURES_FILE = Path(__file__).parent / "agent_features.py"

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
  beach_id, name, county, region, latitude, longitude,
  cdip_distance_km, erddap_distance_km,
  cdip_station_id (str), cdip_station_name (str),
  water_body_class (str), water_body_type (str)
NOTE: stations_df has NO oceanographic measurements — do NOT access salinity, temperature,
wave height, streamflow, or precip from stations_df; those are only in beach_day_df.

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
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": True, "options": options}
    for attempt in range(max_retries):
        try:
            chunks: list[str] = []
            with requests.post(OLLAMA_URL, json=payload, stream=True, timeout=(300, 3600)) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise RuntimeError(data["error"])
                    chunks.append(data.get("response", ""))
                    if data.get("done"):
                        break
            raw = "".join(chunks)
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


def _call_nim(prompt: str, temperature: float = 0.7, max_tokens: int | None = None, max_retries: int = 5) -> str:
    if not _nim_key_pool:
        raise RuntimeError("LLM_PROVIDER=nim but NVIDIA_API_KEYS is not set")
    time.sleep(1.0)  # 60 RPM limit per key, distributed across pool
    current_key = next(_nim_key_pool)
    headers = {
        "Authorization": f"Bearer {current_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "model": _NIM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    for attempt in range(max_retries):
        try:
            resp = requests.post(_NIM_URL, headers=headers, json=payload, timeout=900)
            resp.raise_for_status()
            choices = resp.json().get("choices", [])
            if not choices:
                raise ValueError("No choices in NIM response")
            raw = choices[0].get("message", {}).get("content") or ""
            return re.sub(r"<think>.*?(</think>|$)", "", raw, flags=re.DOTALL).strip()
        except requests.exceptions.HTTPError as exc:
            if exc.response.status_code == 429:
                print(f"  [NIM] rate-limit 429 — sleeping 60s (attempt {attempt+1}/{max_retries})")
                time.sleep(60)
            elif exc.response.status_code in (400, 404):
                raise RuntimeError(f"NIM API error (check model name): {exc.response.text}")
            elif attempt < max_retries - 1:
                time.sleep((attempt + 1) * 5)
            else:
                raise
        except requests.exceptions.Timeout:
            print(f"  [NIM] timeout attempt {attempt+1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 5)
        except Exception as exc:
            print(f"  [NIM] error attempt {attempt+1}/{max_retries}: {exc}")
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 5)
    raise RuntimeError(f"NIM unreachable after {max_retries} retries")


def _call_llm(prompt: str, temperature: float = 0.7, max_tokens: int | None = None) -> str:
    if _LLM_PROVIDER == "nim":
        return _call_nim(prompt, temperature=temperature, max_tokens=max_tokens)
    return _call_ollama(prompt, temperature=temperature, max_tokens=max_tokens)


def _check_ollama() -> None:
    try:
        requests.get(OLLAMA_URL.replace("/api/generate", "/"), timeout=5)
    except requests.ConnectionError:
        raise RuntimeError("Ollama not responding. Start it with: ollama serve")


def _check_nim() -> None:
    if not _NIM_KEYS:
        raise RuntimeError("LLM_PROVIDER=nim but NVIDIA_API_KEYS is not set")
    headers = {"Authorization": f"Bearer {_NIM_KEYS[0]}", "Accept": "application/json"}
    try:
        r = requests.get("https://integrate.api.nvidia.com/v1/models", headers=headers, timeout=10)
        r.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"NIM health check failed: {exc}")


def _check_llm() -> None:
    if _LLM_PROVIDER == "nim":
        _check_nim()
    else:
        _check_ollama()


# ── LLM roles ────────────────────────────────────────────────────────────────

def _ideate(existing_features: str, failed_history: str, kb: str, iteration: int) -> str | None:
    seed_ideas = """
SEED IDEA BANK (these are GOOD starting directions — explore variations):
- tidal-phase interactions: spring/neap tides vs pollution dispersion
- peer-beach exceedance: spatial correlation of pollution among nearby beaches
- lag features: multi-day lagged water quality or weather variables
- AWI × first-flush: atmospheric water index proxy combined with dry-spell breaking rain
- rolling variance: instability of wave or temperature metrics as a predictor
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
- BE CREATIVE and explore genuinely different, orthogonal feature spaces. Don't restrict yourself to simple precip/wave combos.
- Must be computable from beach_day_df, advisories_df, or stations_df alone
- Must use per-beach or per-(beach, time-window) aggregations — no global stats
- Must be computable without leaking future data (no sample at date T can see data after T)

Reply in EXACTLY this format (no Python code):
FEATURE NAME: [snake_case_name]
HYPOTHESIS: [one sentence why this predicts enterococcus exceedance]
IMPLEMENTATION: [3–5 bullet points describing the pandas operations, referencing exact column names]
"""
    try:
        return _call_llm(prompt, temperature=0.9)
    except Exception as exc:
        print(f"  [Ideator] error: {exc}")
        return None


_APPLY_CORRECTION = """
IMPORTANT — your previous attempt used .apply() or transform(lambda). These are HARD-BLOCKED.
Rewrite using ONLY these patterns:
  # Simple arithmetic (no .apply needed):
  df['ratio'] = df['col_a'] / df['col_b'].replace(0, np.nan)
  df['diff']  = df['col_a'] - df['col_b']
  # Rolling per beach (no transform(lambda) needed):
  df['roll'] = df.groupby('beach_id')['col'].rolling(7, min_periods=1, closed='left').mean().reset_index(level=0, drop=True)
  # Z-score per beach (no transform(lambda) needed):
  grp = df.groupby('beach_id')['col']
  df['z'] = (df['col'] - grp.transform('mean')) / (grp.transform('std') + 1e-9)
"""

def _code(idea: str, existing_col_names: str, error_feedback: str = "", attempt: int = 0) -> str | None:
    # Always re-inject the correction block on any retry so the model doesn't regress to .apply/transform(lambda)
    extra_hint = _APPLY_CORRECTION if error_feedback else ""
    error_section = (f"\nPREVIOUS ATTEMPT FAILED — fix this error:\n{error_feedback[:500]}\n{extra_hint}" if error_feedback else "")
    prompt = f"""Write a Python function that engineers a novel beach water-quality feature.

⚠️ AUTO-REJECT PATTERNS — the AST validator will immediately reject code containing ANY of these:
  .apply(...)                                  ← FORBIDDEN
  .transform(lambda ...)                       ← FORBIDDEN

USE THESE INSTEAD (copy verbatim):
  df['ratio'] = df['a'] / df['b'].replace(0, np.nan)
  df['roll']  = df.groupby('beach_id')['col'].rolling(7, min_periods=1, closed='left').mean().reset_index(level=0, drop=True)
  grp = df.groupby('beach_id')['col']
  df['z'] = (df['col'] - grp.transform('mean')) / (grp.transform('std') + 1e-9)

SPEC:
{idea[:800]}

{_SCHEMA_BLOCK}

{error_section}
RULES:
CRITICAL PANDAS RULES (violations cause runtime failures or cross-beach data leakage):
1. Function signature EXACTLY: def build_novel_feature(beach_day_df, advisories_df, stations_df, **kwargs):
2. Return a DataFrame with columns: beach_id, sample_date, <one_new_feature_column> ONLY.
3. Do NOT include exceeds_stv or enterococcus_value in the output.
4. NEVER mutate beach_day_df in place. The very FIRST line of the function body MUST copy:
     df = beach_day_df[['beach_id', 'sample_date', <other_needed_columns>]].copy()
   Any line that writes back to beach_day_df['col'] will be REJECTED by the AST validator.
5. ALL window functions (shift, diff, rolling) MUST be chained off .groupby('beach_id') like:
     df['col'] = df.groupby('beach_id')['target_col'].shift(1)
     df['col'] = df.groupby('beach_id')['target_col'].rolling(window=7, min_periods=1, closed='left').mean().reset_index(level=0, drop=True)
   NEVER call .rolling() directly on a groupby object without first selecting a column.
   ALWAYS groupby('beach_id'). NEVER groupby('county'), groupby('region'), or groupby('cdip_station_id').
6. NEVER use .apply() or transform(lambda ...) — these will be REJECTED by the AST validator.
   FORBIDDEN → ALTERNATIVE (copy these patterns exactly):
   ❌ df.groupby('beach_id')['col'].transform(lambda s: s.rolling(7).mean())
   ✅ df.groupby('beach_id')['col'].rolling(7, min_periods=1, closed='left').mean().reset_index(level=0, drop=True)
   ❌ df['x'] = df.apply(lambda r: r['a'] / r['b'] if r['b'] else 0, axis=1)
   ✅ df['x'] = df['a'] / df['b'].replace(0, np.nan)
   ❌ df.groupby('beach_id')['col'].transform(lambda s: (s - s.mean()) / (s.std() + 1e-9))
   ✅ grp = df.groupby('beach_id')['col']; df['x'] = (df['col'] - grp.transform('mean')) / (grp.transform('std') + 1e-9)
7. No for/while loops. No lambda inside .agg().
8. Add 1e-9 to denominators. Use np.log1p() not np.log().
9. sample_date MUST be preserved as datetime in the output.
10. Avoid column names already in use: {existing_col_names[:200]}

Output ONLY a ```python code block with the complete function including imports.
"""
    try:
        raw = _call_llm(prompt, temperature=0.15)
        match = re.search(r"```python(.*?)```", raw, re.DOTALL)
        if match:
            code = match.group(1).strip()
        else:
            match = re.search(r"```(.*?)```", raw, re.DOTALL)
            if match:
                code = match.group(1).strip()
            else:
                idx = raw.find("def build_novel_feature")
                code = raw[idx:].strip() if idx >= 0 else raw.strip()
        # If the model used a different function name, rename it to the required one
        if "def build_novel_feature(" not in code:
            code = re.sub(
                r"def\s+\w+\s*\(\s*beach_day_df",
                "def build_novel_feature(beach_day_df",
                code,
                count=1,
            )
        return code
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
3. Any .shift(), .diff(), or .rolling() is chained off .groupby('beach_id') to prevent cross-beach leakage?
   (e.g., df.groupby('beach_id')['col'].rolling(7).mean().reset_index(level=0, drop=True) is CORRECT)
4. Any .rolling() uses closed='left'? (prevents current-sample leakage)
5. No for/while loops or .apply()? (performance)
6. No lambda inside .agg()? (performance)
7. Denominators guarded against zero division?
8. Does NOT output exceeds_stv or enterococcus_value columns?

NOTE: advisories_df and stations_df do NOT need to be used in the function body.
The function only needs to accept them in the signature. Do NOT fail for unused parameters.

Reply with exactly "PASS" if all checks pass, or "FAIL: <brief one-sentence reason>" if any check fails.
"""
    try:
        raw = _call_llm(prompt, temperature=0.1)
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
        return _call_llm(prompt, temperature=0.6)
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
        return None, f"Runtime error: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-400:]}"

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


def _cv_metrics(features_df: pd.DataFrame, feat_col: str) -> tuple[float, float, float]:
    """
    Multi-seed county-grouped CV with HistGradientBoostingClassifier.
    Runs _CV_FOLDS folds × len(_CV_SEEDS) seeds.

    Returns (mean_aucpr, mean_brier, boot_ci_10th) where:
      mean_aucpr / mean_brier — averaged over all seeds × folds (reduces HistGBM noise)
      boot_ci_10th — 10th-percentile of 1000-resample bootstrap on seed-averaged OOF probs.
        Use as acceptance test: boot_ci_10th > current_baseline beats point-estimate +δ.

    Pass feat_col NOT in features_df to get baseline metrics.
    GroupKFold on county ensures no county spans train/val — matches prod spatial CV.
    Folds with zero positives in val are skipped (GroupKFold can produce imbalanced splits).
    """
    feature_cols = [c for c in features_df.columns
                    if c not in {"beach_id", "sample_date", "exceeds_stv", "county"}
                    and features_df[c].dtype.kind in "fi"]
    if feat_col in features_df.columns and feat_col not in feature_cols:
        feature_cols.append(feat_col)

    labeled = features_df[feature_cols + ["exceeds_stv", "county"]].replace([np.inf, -np.inf], np.nan)
    labeled = labeled.dropna(subset=["exceeds_stv"])
    X = labeled[feature_cols].fillna(0.0).to_numpy(dtype=np.float32)
    y = labeled["exceeds_stv"].astype(int).to_numpy()
    groups = labeled["county"].fillna("unknown").to_numpy()

    if len(y) < 100:
        return 0.0, 1.0, 0.0

    gkf = GroupKFold(n_splits=_CV_FOLDS)
    splits = list(gkf.split(X, y, groups=groups))

    fold_aucprs: list[float] = []      # one per (fold, seed-averaged) — matches mean stat
    fold_briers: list[float] = []
    oof_y: list[np.ndarray] = []        # one entry per valid fold
    oof_p: list[np.ndarray] = []        # seed-averaged probs

    for train_idx, val_idx in splits:
        if y[val_idx].sum() == 0:
            continue
        seed_probs: list[np.ndarray] = []
        for seed in _CV_SEEDS:
            clf = HistGradientBoostingClassifier(
                max_iter=200,
                max_depth=4,
                learning_rate=0.05,
                min_samples_leaf=30,
                random_state=seed,
            )
            clf.fit(X[train_idx], y[train_idx])
            seed_probs.append(clf.predict_proba(X[val_idx])[:, 1])
        avg_p = np.mean(seed_probs, axis=0)
        fold_aucprs.append(float(average_precision_score(y[val_idx], avg_p)))
        fold_briers.append(float(brier_score_loss(y[val_idx], avg_p)))
        oof_y.append(y[val_idx])
        oof_p.append(avg_p)

    if not fold_aucprs:
        return 0.0, 1.0, 0.0

    mean_aucpr = float(np.mean(fold_aucprs))
    mean_brier = float(np.mean(fold_briers))

    # Block bootstrap: resample within each fold, take per-fold AUCPR, average across folds.
    # Matches the point statistic (mean-of-fold AUCPR) so CI is comparable to baseline.
    rng = np.random.default_rng(42)
    boot_means: list[float] = []
    for _ in range(1000):
        per_fold = []
        for y_fold, p_fold in zip(oof_y, oof_p):
            idx = rng.integers(0, len(y_fold), len(y_fold))
            if y_fold[idx].sum() > 0:
                per_fold.append(float(average_precision_score(y_fold[idx], p_fold[idx])))
        if len(per_fold) == len(oof_y):
            boot_means.append(float(np.mean(per_fold)))
    ci_lower = float(np.percentile(boot_means, 10)) if boot_means else 0.0

    return mean_aucpr, mean_brier, ci_lower


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
    result = enriched[feat_cols + ["beach_id", "sample_date", "exceeds_stv", "county"]].copy()
    return result


def run_loop(max_iterations: int = 50, curated_dir: Path | None = None) -> None:
    if curated_dir is None:
        curated_dir = Path(__file__).resolve().parents[4] / "data" / "curated"

    provider_label = _LLM_PROVIDER.upper()
    model_label = _NIM_MODEL if _LLM_PROVIDER == "nim" else OLLAMA_MODEL
    print("\n--- SURF HEALTH FEATURE-DISCOVERY AGENT ---")
    _check_llm()
    print(f"✅ {provider_label} OK  |  model: {model_label}")
    if _LLM_PROVIDER == "nim":
        print(f"   Keys loaded: {len(_NIM_KEYS)}")
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
    baseline_aucpr, baseline_brier, baseline_ci = _cv_metrics(base_features, feat_col="__dummy__")
    print(f"   Baseline CV ({_CV_FOLDS}-fold × {len(_CV_SEEDS)} seeds):  AUCPR {baseline_aucpr:.4f}  Brier {baseline_brier:.4f}  CI₁₀ {baseline_ci:.4f}")

    existing_fns = _existing_feature_names()
    print(f"   Existing agent features: {len(existing_fns)}")

    start = _start_iteration()
    failed_logs: list[str] = []
    current_features = base_features.copy()
    current_aucpr = baseline_aucpr
    current_brier = baseline_brier

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
            max_corr = float(np.nanmax(augmented[numeric_existing].corrwith(augmented[feat_col]).abs().fillna(0.0)))
            print(f"  📐 Max correlation with existing features: {max_corr:.3f}")
            if max_corr > 0.85:
                msg = f"High correlation ({max_corr:.2f}) with existing features — redundant."
                print(f"  ❌ Correlation gate: {msg}")
                failed_logs.append(f"Idea:\n{idea}\nResult: {msg}")
                _write_iter(i, idea, code, msg, "FAILED (correlation gate)")
                continue

        print(f"  🔄 Running {_CV_FOLDS}-fold × {len(_CV_SEEDS)}-seed CV (county-grouped)...")
        new_aucpr, new_brier, new_ci = _cv_metrics(augmented, feat_col)
        delta_aucpr = new_aucpr - current_aucpr
        delta_brier = new_brier - current_brier
        print(f"  📈 AUCPR: {current_aucpr:.4f} → {new_aucpr:.4f}  ({delta_aucpr:+.4f})  [CI₁₀: {new_ci:.4f}]")
        print(f"  📉 Brier: {current_brier:.4f} → {new_brier:.4f}  ({delta_brier:+.4f})")

        # Gate 1 (AUCPR): bootstrap CI lower bound clears baseline + Brier doesn't degrade
        aucpr_gate = (new_ci > current_aucpr) and (new_brier <= current_brier + _MIN_BRIER_DELTA)
        # Gate 2 (Brier-only): calibration improves, ranking doesn't regress meaningfully
        brier_gate = (new_aucpr >= current_aucpr - _AUCPR_BRIER_ONLY_MAX_REGRESS) and \
                     (new_brier < current_brier - _BRIER_ONLY_MIN_IMPROVEMENT)

        if not aucpr_gate and not brier_gate:
            if brier_gate is False and new_ci <= current_aucpr:
                msg = (f"CI₁₀ {new_ci:.4f} ≤ baseline {current_aucpr:.4f} "
                       f"and Brier gain {-delta_brier:.4f} < {_BRIER_ONLY_MIN_IMPROVEMENT}")
            elif new_brier > current_brier + _MIN_BRIER_DELTA:
                msg = f"Degrades Brier ({current_brier:.4f} → {new_brier:.4f}, limit +{_MIN_BRIER_DELTA})"
            else:
                msg = (f"CI₁₀ {new_ci:.4f} ≤ baseline {current_aucpr:.4f} "
                       f"({current_aucpr:.4f} → {new_aucpr:.4f}  {delta_aucpr:+.4f})")
            failed_logs.append(f"Idea:\n{idea}\nResult: {msg}")
            _write_iter(i, idea, code, msg, "FAILED (CV gate)",
                        f"Uni: {uni:.4f} | AUCPR: {new_aucpr:.4f} CI₁₀: {new_ci:.4f} | Brier: {new_brier:.4f}")
            continue

        gate_label = "AUCPR+CI" if aucpr_gate else "Brier-only"

        # ── ACCEPT ──
        print(f"  🎉 ACCEPTED [{gate_label}]: {feat_col}")
        _persist(code, i)
        current_features = augmented.copy()
        current_aucpr = new_aucpr
        current_brier = new_brier
        _write_iter(i, idea, code, "", f"SUCCESS ({gate_label})",
                    f"Uni: {uni:.4f} | AUCPR: {new_aucpr:.4f} ({delta_aucpr:+.4f}) CI₁₀: {new_ci:.4f} | Brier: {new_brier:.4f} ({delta_brier:+.4f})")
        failed_logs.clear()

    print(f"\n--- Done. Final AUCPR: {current_aucpr:.4f} (started {baseline_aucpr:.4f})  Brier: {current_brier:.4f} (started {baseline_brier:.4f}) ---")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Surf Health feature-discovery agent")
    ap.add_argument("--iterations", type=int, default=50)
    ap.add_argument("--curated", type=Path, default=None, help="Path to data/curated/")
    args = ap.parse_args()
    run_loop(max_iterations=args.iterations, curated_dir=args.curated)
