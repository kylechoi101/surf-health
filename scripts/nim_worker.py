#!/usr/bin/env python3
"""NIM/Ollama worker — continues deployment work from order.txt.

Reads order.txt, runs an agentic tool-use loop (bash / read_file / write_file)
to verify real state, then produces a WORK_LOG entry and optionally updates
order.txt. Loops until STATUS: DONE or --max-iters is reached.

Usage
-----
    # NIM cloud (default)
    NVIDIA_API_KEYS="key1,key2" scripts/nim_worker.py
    scripts/nim_worker.py --sleep 60 --max-iters 20

    # Local Ollama
    scripts/nim_worker.py --backend ollama --models gemma4:31b

    # Dry-run (no file writes, no git commits)
    scripts/nim_worker.py --no-write

    # Safety limits
    scripts/nim_worker.py --max-bash-failures 5 --budget-usd 3.00

NIM model catalog: https://docs.api.nvidia.com/nim/reference/llm-apis#models
Ollama endpoint:   http://localhost:11434/v1/chat/completions  (OpenAI-compat)
"""
from __future__ import annotations

import argparse
import datetime as _dt
from dataclasses import dataclass
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
ORDER_PATH = REPO_ROOT / "order.txt"
LOG_PATH = REPO_ROOT / "nim_worker.log"
HISTORY_DIR = REPO_ROOT / ".order_history"

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
OLLAMA_BASE_URL = "http://localhost:11434/v1"

DEFAULT_NIM_MODELS = [
    "meta/llama-3.3-70b-instruct",
    "qwen/qwen2.5-coder-32b-instruct",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "mistralai/mixtral-8x22b-instruct-v0.1",
]
DEFAULT_OLLAMA_MODELS = ["gemma4:31b"]

# Approximate NIM token pricing (USD per 1M tokens, input+output blended).
# Used only when --budget-usd is set.
_NIM_PRICING: dict[str, float] = {
    "meta/llama-3.3-70b-instruct": 0.23,
    "qwen/qwen2.5-coder-32b-instruct": 0.40,
    "nvidia/llama-3.1-nemotron-70b-instruct": 0.35,
    "mistralai/mixtral-8x22b-instruct-v0.1": 0.50,
    "meta/llama-3.1-405b-instruct": 1.60,
    "deepseek-ai/deepseek-r1": 0.55,
}
_DEFAULT_PRICE_PER_M = 0.50  # conservative fallback

MAX_TOOL_ROUNDS = 24  # max tool-call turns per outer iteration

# ---------------------------------------------------------------------------
# Bash sandbox
# ---------------------------------------------------------------------------

# Patterns that are ALWAYS denied regardless of allow-list.
_BASH_DENY_RE = re.compile(
    r"""(
          rm\s+-rf
        | rm\s+--recursive
        | git\s+(push\s+.*--force|push\s+.*-f\b)   # force push
        | >\s*/dev/\w+                               # overwrite device files
        | /\.ssh/
        | kubectl\b
        | \baws\b
        | \bgcloud\b
        | \bheroku\b
        | \bsudo\b
        | \bchmod\b
        | \bchown\b
        | base64\s+--decode
        | curl\s+.*-o\s+(?!/dev/null)               # curl download to non-null
    )""",
    re.VERBOSE | re.IGNORECASE,
)

# Commands that are explicitly allowed (prefix match on the stripped cmd).
_BASH_ALLOW_PREFIXES = (
    "git status",
    "git log",
    "git diff",
    "git show",
    "git add",
    "git rm",
    "git commit",
    "git push",
    "git branch",
    "git stash",
    "gh run list",
    "gh run view",
    "gh run watch",
    "gh pr list",
    "gh pr view",
    "npm run build",
    "npm run dev",
    "npm run lint",
    "npx tsc",
    "npx lighthouse",
    "npx expo",
    "eas ",
    "cd web &&",
    "cd backend &&",
    "cd /Users/kylechoi/surf_health",
    "curl -s",
    "curl -sL",
    "python3 -c",
    "python -c",
    ".venv/bin/python",
    "backend/.venv/bin/python",
    "grep ",
    "find .",
    "ls ",
    "cat ",
    "head ",
    "tail ",
    "sed -n ",
    "wc ",
    "echo ",
    "node -e",
    "jq ",
    "dig ",
)


def _sandbox_check(cmd: str) -> str | None:
    """Return an error string if the command is denied, else None."""
    stripped = cmd.strip()
    if _BASH_DENY_RE.search(stripped):
        return f"SANDBOX DENY: command matches a prohibited pattern."
    if not any(stripped.startswith(p) for p in _BASH_ALLOW_PREFIXES):
        return (
            f"SANDBOX DENY: command '{stripped[:80]}' does not match any "
            "allowed prefix. Add it to _BASH_ALLOW_PREFIXES if it's safe."
        )
    return None


# Bash commands that mutate repo state — blocked in --no-write mode.
_BASH_MUTATING_RE = re.compile(
    r"git\s+(commit|push|rm|add|stash\b)", re.IGNORECASE
)


def _execute_bash(cmd: str, timeout: int = 60, no_write: bool = False) -> str:
    deny = _sandbox_check(cmd)
    if deny:
        return deny
    if no_write and _BASH_MUTATING_RE.search(cmd):
        return f"DRY-RUN (--no-write): would execute: {cmd[:200]}"
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = result.stdout + result.stderr
        if len(out) > 8000:
            out = out[:7800] + "\n…[truncated]"
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s"
    except Exception as e:
        return f"ERROR: {e!r}"


def _execute_read_file(path: str) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    try:
        p = p.resolve()
    except Exception:
        return f"ERROR: cannot resolve path {path!r}"
    if not str(p).startswith(str(REPO_ROOT)):
        return f"SANDBOX DENY: path is outside repo root."
    if not p.exists():
        return f"ERROR: file not found: {p}"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > 12000:
            content = content[:11800] + "\n…[truncated]"
        return content
    except Exception as e:
        return f"ERROR reading {p}: {e!r}"


def _execute_write_file(path: str, content: str, no_write: bool = False) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    try:
        p = p.resolve()
    except Exception:
        return f"ERROR: cannot resolve path {path!r}"
    if not str(p).startswith(str(REPO_ROOT)):
        return f"SANDBOX DENY: path is outside repo root."
    # Protect secrets
    if p.name in (".env", ".env.local", "secrets.json", "credentials.json"):
        return f"SANDBOX DENY: refusing to write {p.name}."
    if no_write:
        return f"DRY-RUN: would write {len(content)} chars to {p.relative_to(REPO_ROOT)}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"OK: wrote {len(content)} chars to {p.relative_to(REPO_ROOT)}"


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI format)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Run a shell command in the repo root. Output is returned as a string. "
                "Use this to check build status, run tests, inspect git state, read logs, "
                "or make commits. Sandbox enforces an allowlist; denied commands return "
                "SANDBOX DENY."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "The shell command to run."},
                    "timeout": {
                        "type": "integer",
                        "description": "Max seconds to wait (default 60, max 300).",
                        "default": 60,
                    },
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a text file from the repo. Path may be relative to repo root or absolute. "
                "Files outside the repo are denied."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path (relative or absolute)."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write content to a file in the repo. Creates parent directories if needed. "
                "Refuses to write .env / secrets files. In --no-write mode, reports "
                "what would be written but does not touch disk."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path (relative or absolute)."},
                    "content": {"type": "string", "description": "Full file content to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a deployment-helper agent continuing work on the Surf Health / Shorelife project. You receive the current order.txt — a structured handoff with blockers, status, and next steps.

You have three tools:
  bash(cmd)             — run shell commands (sandboxed allowlist)
  read_file(path)       — read any file in the repo
  write_file(path, content) — write a file in the repo

Workflow per iteration:
1. Read order.txt (already in your context).
2. Pick the highest-priority unblocked item that is NOT already marked complete.
3. Use tools to VERIFY the actual current state before deciding what to do.
   Never trust a status claim in order.txt without checking. Run `npm run build`,
   `gh run list`, `curl`, `git status` — whatever is needed to ground truth.
4. Take concrete action: run builds, write code fixes, make commits, push.
5. When done with tool calls, output EXACTLY:

<WORK_LOG>
[what you did, what you found, what commands ran, under 400 words]
</WORK_LOG>
<UPDATED_ORDER>
[full updated order.txt content — preserve structure, update status flags,
 mark shipped items, tighten next-steps. Do NOT delete history.]
</UPDATED_ORDER>

Rules:
- If bash returns SANDBOX DENY, do NOT attempt to work around it. Report it.
- If npm run build fails, diagnose from the output before proposing a fix.
- If git push fails, STOP and report — do not retry or force.
- Only mark an item complete in UPDATED_ORDER if you actually confirmed it
  (commit hash in `git log`, 200 from curl, etc.).
- No prose outside the tags in your final output."""

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _ts() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg: str) -> None:
    line = f"[{_ts()}] {msg}\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)


# ---------------------------------------------------------------------------
# order.txt helpers
# ---------------------------------------------------------------------------


def _read_order() -> str:
    return ORDER_PATH.read_text(encoding="utf-8")


def _write_order(new_content: str) -> Path:
    HISTORY_DIR.mkdir(exist_ok=True)
    stamp = _ts().replace(":", "").replace("-", "")
    backup = HISTORY_DIR / f"order.{stamp}.txt"
    backup.write_text(_read_order(), encoding="utf-8")
    tmp = ORDER_PATH.with_suffix(".txt.tmp")
    tmp.write_text(new_content, encoding="utf-8")
    tmp.replace(ORDER_PATH)
    return backup


def _is_done(order_text: str) -> bool:
    return bool(re.search(r"^STATUS:\s*DONE\b", order_text, re.MULTILINE))


def _parse_response(text: str) -> tuple[str | None, str | None]:
    work = re.search(r"<WORK_LOG>(.*?)</WORK_LOG>", text, re.DOTALL)
    order = re.search(r"<UPDATED_ORDER>(.*?)</UPDATED_ORDER>", text, re.DOTALL)
    return (
        work.group(1).strip() if work else None,
        order.group(1).strip() if order else None,
    )


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------


def _call_api(
    base_url: str,
    api_key: str | None,
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    timeout: int = 240,
) -> dict:
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": 8192,
        "temperature": 0.2,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    # Ollama can be slow on large models; auto-bump its timeout
    if "11434" in base_url and timeout < 600:
        timeout = 600

    url = f"{base_url.rstrip('/')}/chat/completions"
    r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Token budget tracking
# ---------------------------------------------------------------------------


def _tokens_cost(response: dict, model: str) -> float:
    usage = response.get("usage", {})
    total = usage.get("total_tokens", 0)
    price_per_m = _NIM_PRICING.get(model, _DEFAULT_PRICE_PER_M)
    return total * price_per_m / 1_000_000


# ---------------------------------------------------------------------------
# Agentic iteration
# ---------------------------------------------------------------------------


def _run_iteration(
    base_url: str,
    api_key: str | None,
    model: str,
    order_text: str,
    no_write: bool,
    max_bash_failures: int,
) -> tuple[str | None, str | None, float]:
    """Run one outer iteration. Returns (work_log, updated_order, cost_usd)."""
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Current order.txt:\n\n{order_text}"},
    ]
    total_cost = 0.0
    bash_failures = 0

    for round_i in range(MAX_TOOL_ROUNDS):
        try:
            resp = _call_api(base_url, api_key, model, messages, tools=TOOLS)
        except requests.HTTPError as e:
            body = getattr(e.response, "text", "")[:400] if e.response is not None else ""
            _log(f"  HTTP error round {round_i}: {e} | {body}")
            return None, None, total_cost

        total_cost += _tokens_cost(resp, model)
        choice = resp["choices"][0]
        msg = choice["message"]
        finish = choice.get("finish_reason", "")
        tool_calls = msg.get("tool_calls") or []

        # Append assistant message to history
        messages.append(msg)

        if not tool_calls:
            # Model is done with tools — extract tags from content
            content = msg.get("content") or ""
            work_log, updated_order = _parse_response(content)
            if not work_log and not updated_order:
                _log(f"  WARN round {round_i}: no tags in final message. head: {content[:200]!r}")
            return work_log, updated_order, total_cost

        # Execute tool calls
        _log(f"  round {round_i}: {len(tool_calls)} tool call(s)")
        tool_results: list[dict] = []
        for tc in tool_calls:
            fn = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}

            if fn == "bash":
                cmd = args.get("cmd", "")
                timeout = min(int(args.get("timeout", 60)), 300)
                _log(f"    bash: {cmd[:120]!r}")
                result = _execute_bash(cmd, timeout=timeout, no_write=no_write)
                # Only count real execution errors, not sandbox denies.
                # SANDBOX DENY is just "try a different command" feedback.
                if result.startswith("ERROR") or result.startswith("TIMEOUT"):
                    bash_failures += 1
                _log(f"    → {result[:200]!r}")
            elif fn == "read_file":
                path = args.get("path", "")
                _log(f"    read_file: {path!r}")
                result = _execute_read_file(path)
                _log(f"    → {len(result)} chars")
            elif fn == "write_file":
                path = args.get("path", "")
                content = args.get("content", "")
                _log(f"    write_file: {path!r} ({len(content)} chars)")
                result = _execute_write_file(path, content, no_write=no_write)
                _log(f"    → {result}")
            else:
                result = f"ERROR: unknown tool '{fn}'"

            tool_results.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

            if bash_failures >= max_bash_failures:
                _log(f"  STOP: reached --max-bash-failures={max_bash_failures}")
                messages.extend(tool_results)
                return None, None, total_cost

        messages.extend(tool_results)

    _log(f"  WARN: hit MAX_TOOL_ROUNDS={MAX_TOOL_ROUNDS} without final output")
    return None, None, total_cost


# ---------------------------------------------------------------------------
# Hybrid mode — Plan dataclass + NIM/Ollama helpers
# ---------------------------------------------------------------------------

HYBRID_MAX_EXECUTOR_ROUNDS = 5


@dataclass
class Plan:
    decision: str        # "continue" | "DONE"
    goal: str
    action_list: list[str]
    exit_criterion: str


_NIM_PLANNER_SYSTEM = """\
You are the BRAIN in a NIM-brain/Ollama-executor hybrid agent for the Surf Health / Shorelife project.

Read the current order.txt and the executor's prior digest. Emit a compact JSON PLAN for the executor.

Output ONLY valid JSON (no prose, no markdown fences):
{
  "decision": "continue",
  "goal": "one-sentence goal for this iteration",
  "action_list": ["step 1: specific tool + command", "step 2"],
  "exit_criterion": "exact condition executor must verify before stopping"
}

Rules:
- Set decision="DONE" if STATUS: DONE appears in order.txt or all priorities are already complete.
- action_list: 1-3 items. Each item = one or two tool calls with a concrete command.
- Total output ≤ 300 tokens.
- The executor never sees order.txt directly — give it enough context in action_list steps.
- Pick the highest-priority unblocked WORKER item from the order.txt NEXT STEPS section.
"""

_NIM_UPDATE_SYSTEM = """\
You are the BRAIN in a NIM-brain/Ollama-executor hybrid agent for the Surf Health / Shorelife project.

The executor finished a task. Review its digest and produce an updated order.txt.

Output ONLY the updated order.txt inside these tags (no prose outside):
<UPDATED_ORDER>
[full updated order.txt content]
</UPDATED_ORDER>

Rules:
- Only mark items [✅] complete if the executor's digest confirms it (commit hash, curl 200, etc.).
- Preserve all sections and history; do not delete anything.
- Increment the revision number if a meaningful step completed.
"""

_EXECUTOR_SYSTEM_TEMPLATE = """\
You are the EXECUTOR in a NIM-brain/Ollama-executor hybrid agent for the Surf Health / Shorelife project.

PLAN FROM BRAIN:
  Goal: {goal}
  Steps:
{steps}
  Exit criterion: {exit_criterion}

You have three tools:
  bash(cmd)                   — run shell commands (sandboxed allowlist)
  read_file(path)             — read any file in the repo
  write_file(path, content)   — write a file in the repo

Execute the plan step by step. Stop when exit_criterion is met (verify explicitly).
Max {max_rounds} tool-call rounds total; if exhausted without meeting exit_criterion, say so.

When done, output EXACTLY:
<DIGEST>
[≤500 words: what you did, commands run, what worked, what failed, commit SHAs or file paths, whether exit_criterion was met]
</DIGEST>

No prose outside the <DIGEST> tags in your final output.
"""


def _nim_plan(
    base_url: str,
    api_key: str | None,
    model: str,
    order_text: str,
    prior_digest: str,
) -> tuple[Plan, float]:
    """Single NIM call → Plan dataclass + cost_usd."""
    messages = [
        {"role": "system", "content": _NIM_PLANNER_SYSTEM},
        {
            "role": "user",
            "content": f"order.txt:\n\n{order_text}\n\nPrior executor digest:\n{prior_digest}",
        },
    ]
    resp = _call_api(base_url, api_key, model, messages, tools=None)
    cost = _tokens_cost(resp, model)

    raw = resp["choices"][0]["message"].get("content", "").strip()
    # Strip markdown fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\n?```\s*$", "", raw.strip(), flags=re.MULTILINE)

    try:
        data = json.loads(raw.strip())
        plan = Plan(
            decision=data.get("decision", "continue"),
            goal=data.get("goal", ""),
            action_list=data.get("action_list", []),
            exit_criterion=data.get("exit_criterion", ""),
        )
    except json.JSONDecodeError:
        _log(f"  WARN: could not parse planner JSON; raw={raw[:200]!r}")
        plan = Plan(
            decision="continue",
            goal="Diagnose current state (planner JSON parse failed)",
            action_list=["bash: git status && git log --oneline -5", "read_file: order.txt"],
            exit_criterion="Any tool output received",
        )
    return plan, cost


def _ollama_execute(
    base_url: str,
    api_key: str | None,
    model: str,
    plan: Plan,
    no_write: bool,
    max_bash_failures: int,
    max_rounds: int = HYBRID_MAX_EXECUTOR_ROUNDS,
) -> tuple[str, int, str, float]:
    """Run executor tool loop. Returns (digest, rounds_used, exit_reason, cost_usd)."""
    steps_text = "\n".join(f"    {i + 1}. {s}" for i, s in enumerate(plan.action_list))
    system_prompt = _EXECUTOR_SYSTEM_TEMPLATE.format(
        goal=plan.goal,
        steps=steps_text,
        exit_criterion=plan.exit_criterion,
        max_rounds=max_rounds,
    )
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Begin executing the plan."},
    ]
    bash_failures = 0
    total_cost = 0.0

    for round_i in range(max_rounds):
        try:
            resp = _call_api(base_url, api_key, model, messages, tools=TOOLS)
        except requests.HTTPError as e:
            body = getattr(e.response, "text", "")[:300] if e.response is not None else ""
            _log(f"    executor HTTP error round {round_i}: {e} | {body}")
            return f"HTTP error: {e}", round_i, "http_error", total_cost

        total_cost += _tokens_cost(resp, model)
        choice = resp["choices"][0]
        msg = choice["message"]
        tool_calls = msg.get("tool_calls") or []
        messages.append(msg)

        if not tool_calls:
            content = msg.get("content") or ""
            m = re.search(r"<DIGEST>(.*?)</DIGEST>", content, re.DOTALL)
            if m:
                return m.group(1).strip(), round_i, "digest_tag", total_cost
            _log(f"    executor round {round_i}: no tool calls, no DIGEST tag")
            return content[:500] or "(empty)", round_i, "no_digest_tag", total_cost

        _log(f"    executor round {round_i}: {len(tool_calls)} tool call(s)")
        tool_results: list[dict] = []
        for tc in tool_calls:
            fn = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}

            if fn == "bash":
                cmd = args.get("cmd", "")
                timeout = min(int(args.get("timeout", 60)), 300)
                _log(f"      bash: {cmd[:120]!r}")
                result = _execute_bash(cmd, timeout=timeout, no_write=no_write)
                if result.startswith("ERROR") or result.startswith("TIMEOUT"):
                    bash_failures += 1
                _log(f"      → {result[:200]!r}")
            elif fn == "read_file":
                path = args.get("path", "")
                _log(f"      read_file: {path!r}")
                result = _execute_read_file(path)
                _log(f"      → {len(result)} chars")
            elif fn == "write_file":
                path = args.get("path", "")
                content_w = args.get("content", "")
                _log(f"      write_file: {path!r} ({len(content_w)} chars)")
                result = _execute_write_file(path, content_w, no_write=no_write)
                _log(f"      → {result}")
            else:
                result = f"ERROR: unknown tool '{fn}'"

            tool_results.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

            if bash_failures >= max_bash_failures:
                _log(f"    executor STOP: bash_failures={bash_failures}")
                messages.extend(tool_results)
                return f"Stopped: bash failures={bash_failures}", round_i, "bash_failures", total_cost

        messages.extend(tool_results)

    return "(max rounds exhausted)", round_i + 1, "max_rounds", total_cost


def _nim_update_order(
    base_url: str,
    api_key: str | None,
    model: str,
    order_text: str,
    plan: Plan,
    digest: str,
) -> tuple[str | None, float]:
    """Single NIM call → (updated_order_text, cost_usd)."""
    user_content = (
        f"Current order.txt:\n\n{order_text}\n\n"
        f"Plan executed:\n"
        f"  Goal: {plan.goal}\n"
        f"  Steps: {plan.action_list}\n"
        f"  Exit criterion: {plan.exit_criterion}\n\n"
        f"Executor digest:\n{digest}"
    )
    messages = [
        {"role": "system", "content": _NIM_UPDATE_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    resp = _call_api(base_url, api_key, model, messages, tools=None)
    cost = _tokens_cost(resp, model)
    raw = resp["choices"][0]["message"].get("content", "")
    m = re.search(r"<UPDATED_ORDER>(.*?)</UPDATED_ORDER>", raw, re.DOTALL)
    if m:
        return m.group(1).strip(), cost
    _log(f"  WARN: no <UPDATED_ORDER> in NIM update response; head: {raw[:200]!r}")
    return None, cost


def _run_hybrid(
    planner_url: str,
    planner_key: str | None,
    planner_model: str,
    executor_url: str,
    executor_model: str,
    max_iters: int,
    max_bash_failures: int,
    executor_rounds: int,
    no_write: bool,
    budget_usd: float,
    sleep_s: int,
) -> int:
    """Outer loop for hybrid NIM-brain / Ollama-executor mode."""
    if not ORDER_PATH.exists():
        print(f"ERROR: {ORDER_PATH} not found", file=sys.stderr)
        return 2

    _log(
        f"hybrid starting | planner={planner_model} | executor={executor_model} | "
        f"max-iters={max_iters} | executor-rounds={executor_rounds} | "
        f"write={not no_write} | budget=${budget_usd:.2f}"
    )

    prior_digest = "(first iteration; no prior digest)"
    total_cost = 0.0
    iters = 0

    while True:
        if max_iters and iters >= max_iters:
            _log(f"Reached --max-iters={max_iters}, exiting")
            break
        iters += 1

        order_text = _read_order()
        if _is_done(order_text):
            _log("order.txt has STATUS: DONE — exiting")
            break

        _log(f"--- hybrid iter {iters} | planner={planner_model} ---")

        # 1 NIM plan call
        t0 = time.time()
        try:
            plan, plan_cost = _nim_plan(
                planner_url, planner_key, planner_model, order_text, prior_digest
            )
        except Exception as e:
            _log(f"NIM plan error: {e!r}")
            time.sleep(sleep_s)
            continue

        plan_wall = time.time() - t0
        total_cost += plan_cost
        _log(
            f"  NIM plan | decision={plan.decision} | goal={plan.goal[:80]!r} | "
            f"cost=${plan_cost:.4f} | wall={plan_wall:.1f}s"
        )

        if plan.decision == "DONE":
            _log("NIM decided DONE — exiting hybrid loop")
            break

        if budget_usd > 0 and total_cost >= budget_usd:
            _log(f"Budget ${budget_usd:.2f} reached before executor (${total_cost:.4f}), exiting")
            break

        # 1..N Ollama executor tool-call rounds
        t1 = time.time()
        try:
            digest, rounds_used, exit_reason, exec_cost = _ollama_execute(
                executor_url, None, executor_model, plan,
                no_write=no_write,
                max_bash_failures=max_bash_failures,
                max_rounds=executor_rounds,
            )
        except Exception as e:
            _log(f"Ollama executor error: {e!r}")
            prior_digest = f"Executor errored: {e!r}"
            time.sleep(sleep_s)
            continue

        exec_wall = time.time() - t1
        total_cost += exec_cost
        _log(
            f"  Ollama exec | rounds={rounds_used} | exit={exit_reason} | "
            f"wall={exec_wall:.1f}s | cost=${exec_cost:.4f}"
        )
        _log(f"  digest: {digest[:300]!r}")

        # 1 NIM update call
        t2 = time.time()
        try:
            updated_order, update_cost = _nim_update_order(
                planner_url, planner_key, planner_model, order_text, plan, digest
            )
        except Exception as e:
            _log(f"NIM update error: {e!r}")
            prior_digest = digest
            time.sleep(sleep_s)
            continue

        update_wall = time.time() - t2
        total_cost += update_cost
        _log(
            f"  NIM update | cost=${update_cost:.4f} | wall={update_wall:.1f}s | "
            f"cumulative NIM=${total_cost:.4f}"
        )

        if updated_order and not no_write:
            if updated_order.strip() == order_text.strip():
                _log("  order.txt unchanged this iteration")
            else:
                backup = _write_order(updated_order)
                _log(f"  order.txt updated; prior backed up to {backup.relative_to(REPO_ROOT)}")
        elif not updated_order:
            _log("  WARN: no updated order from NIM; order.txt left untouched")

        prior_digest = digest

        if budget_usd > 0 and total_cost >= budget_usd:
            _log(f"Budget ${budget_usd:.2f} reached (${total_cost:.4f}), exiting")
            break

        time.sleep(sleep_s)

    _log(f"hybrid done | iters={iters} | total NIM cost=${total_cost:.4f}")
    return 0


# ---------------------------------------------------------------------------
# Key / model loading
# ---------------------------------------------------------------------------


def _load_nim_keys() -> list[str]:
    multi = os.environ.get("NVIDIA_API_KEYS", "")
    keys = [k.strip() for k in multi.split(",") if k.strip()]
    if not keys:
        single = os.environ.get("NVIDIA_API_KEY", "").strip()
        if single:
            keys = [single]
    return keys


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--backend", choices=["nim", "ollama"], default="nim",
        help="LLM backend: 'nim' (NVIDIA cloud) or 'ollama' (local, default model gemma4:31b)",
    )
    parser.add_argument(
        "--models",
        help="Comma-separated model IDs (default depends on --backend)",
    )
    parser.add_argument("--sleep", type=int, default=60, help="Seconds between iterations (default 60)")
    parser.add_argument("--max-iters", type=int, default=0, help="Stop after N iterations (0 = run forever)")
    parser.add_argument("--no-write", action="store_true", help="Don't update order.txt or write files, just log")
    parser.add_argument(
        "--max-bash-failures", type=int, default=10,
        help="Stop the iteration if bash/sandbox errors exceed this count (default 10)",
    )
    parser.add_argument(
        "--budget-usd", type=float, default=0.0,
        help="Stop the worker when cumulative NIM spend exceeds this USD amount (0 = unlimited)",
    )
    parser.add_argument(
        "--mode", choices=["single", "hybrid"], default="single",
        help=(
            "'single': one backend does everything (default). "
            "'hybrid': NIM brain plans, Ollama executor runs tool loop."
        ),
    )
    parser.add_argument(
        "--planner-model",
        help="(hybrid only) NIM model to use as the planning brain (default: first NIM model)",
    )
    parser.add_argument(
        "--executor-model",
        help="(hybrid only) Ollama model for the executor (default: gemma4:31b)",
    )
    parser.add_argument(
        "--executor-rounds", type=int, default=HYBRID_MAX_EXECUTOR_ROUNDS,
        help=f"(hybrid only) Max tool-call rounds per executor session (default {HYBRID_MAX_EXECUTOR_ROUNDS})",
    )
    args = parser.parse_args()

    # Hybrid mode dispatch — before single-backend setup
    if args.mode == "hybrid":
        nim_keys = _load_nim_keys()
        if not nim_keys:
            print(
                "ERROR: set NVIDIA_API_KEYS or NVIDIA_API_KEY for hybrid planner",
                file=sys.stderr,
            )
            return 2
        planner_model = args.planner_model or DEFAULT_NIM_MODELS[0]
        executor_model = args.executor_model or DEFAULT_OLLAMA_MODELS[0]
        return _run_hybrid(
            planner_url=NIM_BASE_URL,
            planner_key=nim_keys[0],
            planner_model=planner_model,
            executor_url=OLLAMA_BASE_URL,
            executor_model=executor_model,
            max_iters=args.max_iters,
            max_bash_failures=args.max_bash_failures,
            executor_rounds=args.executor_rounds,
            no_write=args.no_write,
            budget_usd=args.budget_usd,
            sleep_s=args.sleep,
        )

    # Resolve backend
    if args.backend == "nim":
        base_url = NIM_BASE_URL
        keys = _load_nim_keys()
        if not keys:
            print("ERROR: set NVIDIA_API_KEYS or NVIDIA_API_KEY for --backend nim", file=sys.stderr)
            return 2
        default_models = DEFAULT_NIM_MODELS
    else:  # ollama
        base_url = OLLAMA_BASE_URL
        keys = [None]  # no auth
        default_models = DEFAULT_OLLAMA_MODELS

    models_str = args.models or ",".join(default_models)
    models = [m.strip() for m in models_str.split(",") if m.strip()]
    if not models:
        print("ERROR: empty model list", file=sys.stderr)
        return 2

    if not ORDER_PATH.exists():
        print(f"ERROR: {ORDER_PATH} not found", file=sys.stderr)
        return 2

    _log(
        f"worker starting | backend={args.backend} | {len(keys)} key(s) | "
        f"{len(models)} model(s) | sleep={args.sleep}s | write={not args.no_write} | "
        f"max-bash-failures={args.max_bash_failures} | budget=${args.budget_usd:.2f}"
    )
    _log(f"models: {models}")

    keys_iter = itertools.cycle(keys)
    models_iter = itertools.cycle(models)
    iters = 0
    total_cost = 0.0

    while True:
        iters += 1
        if args.max_iters and iters > args.max_iters:
            _log(f"Reached --max-iters={args.max_iters}, exiting")
            break

        order_text = _read_order()
        if _is_done(order_text):
            _log("order.txt has STATUS: DONE — exiting")
            break

        model = next(models_iter)
        key = next(keys_iter)
        _log(f"--- iter {iters} | model={model} ---")

        try:
            work_log, updated_order, cost = _run_iteration(
                base_url=base_url,
                api_key=key,
                model=model,
                order_text=order_text,
                no_write=args.no_write,
                max_bash_failures=args.max_bash_failures,
            )
        except requests.HTTPError as e:
            body = getattr(e.response, "text", "")[:500] if e.response is not None else ""
            _log(f"HTTP error from {model}: {e} | body: {body}")
            time.sleep(args.sleep)
            continue
        except Exception as e:
            _log(f"call failed ({model}): {e!r}")
            time.sleep(args.sleep)
            continue

        total_cost += cost
        _log(f"iter {iters} cost: ${cost:.4f} | cumulative: ${total_cost:.4f}")

        if args.budget_usd > 0 and total_cost >= args.budget_usd:
            _log(f"Budget ${args.budget_usd:.2f} reached (spent ${total_cost:.4f}), exiting")
            break

        if work_log:
            _log(f"WORK_LOG ({model}):\n{work_log}\n")
        else:
            _log(f"WARN: no <WORK_LOG> tag in reply from {model}")

        if updated_order and not args.no_write:
            if updated_order.strip() == order_text.strip():
                _log("order.txt unchanged this iteration")
            else:
                backup = _write_order(updated_order)
                _log(f"order.txt updated; prior backed up to {backup.relative_to(REPO_ROOT)}")
        elif not updated_order:
            _log("WARN: no <UPDATED_ORDER> tag; order.txt left untouched")

        time.sleep(args.sleep)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
