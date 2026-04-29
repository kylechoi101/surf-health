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
from typing import Any, Annotated, List, Literal, TypedDict
import operator

try:
    from langgraph.graph import StateGraph, START, END
    from langgraph.prebuilt import ToolNode
    from langchain_nvidia_ai_endpoints import ChatNVIDIA
    from langchain_ollama import ChatOllama
    from langchain_core.messages import SystemMessage, HumanMessage, AnyMessage
    from langchain_core.tools import tool
    LANGGRAPH_AVAILABLE = True

    class WorkerState(TypedDict):
        messages: Annotated[List[AnyMessage], operator.add]
        order_text: str
        current_plan: str
        updated_order: str
        task_done: bool
        total_cost: float
except ImportError:
    LANGGRAPH_AVAILABLE = False
    AnyMessage = Any # dummy type for globals

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
# Hybrid mode — LangGraph Implementation
# ---------------------------------------------------------------------------

HYBRID_MAX_EXECUTOR_ROUNDS = 5

def _run_hybrid(
    planner_url: str,
    planner_key: str | None,
    planner_model_name: str,
    executor_url: str,
    executor_model_name: str,
    max_iters: int,
    max_bash_failures: int,
    executor_rounds: int,
    no_write: bool,
    budget_usd: float,
    sleep_s: int,
) -> int:
    """Outer loop for hybrid NIM-brain / Ollama-executor mode using LangGraph."""
    if not LANGGRAPH_AVAILABLE:
        print("ERROR: Hybrid mode requires langgraph. Install dependencies first.", file=sys.stderr)
        return 2

    if not ORDER_PATH.exists():
        print(f"ERROR: {ORDER_PATH} not found", file=sys.stderr)
        return 2

    _log(
        f"hybrid starting (LangGraph) | planner={planner_model_name} | executor={executor_model_name} | "
        f"max-iters={max_iters} | executor-rounds={executor_rounds} | "
        f"write={not no_write} | budget=${budget_usd:.2f}"
    )

    nim_keys = _load_nim_keys()
    if not nim_keys:
        print("ERROR: set NVIDIA_API_KEYS for hybrid planner", file=sys.stderr)
        return 2
    key_iterator = itertools.cycle(nim_keys)

    # Define LangChain Tools wrapping our sandbox
    @tool
    def bash(cmd: str, timeout: int = 60) -> str:
        """Run a shell command in the repo root. Output is returned as a string. Use this to check build status, run tests, inspect git state, read logs, or make commits. Sandbox enforces an allowlist; denied commands return SANDBOX DENY."""
        _log(f"    [TOOL] bash: {cmd[:120]!r}")
        result = _execute_bash(cmd, timeout=timeout, no_write=no_write)
        _log(f"    → {result[:200]!r}")
        return result

    @tool
    def read_file(path: str) -> str:
        """Read a text file from the repo. Path may be relative to repo root or absolute."""
        _log(f"    [TOOL] read_file: {path!r}")
        result = _execute_read_file(path)
        _log(f"    → {len(result)} chars")
        return result

    @tool
    def write_file(path: str, content: str) -> str:
        """Write content to a file in the repo. Creates parent directories if needed. Refuses to write .env / secrets files."""
        _log(f"    [TOOL] write_file: {path!r} ({len(content)} chars)")
        result = _execute_write_file(path, content, no_write=no_write)
        _log(f"    → {result}")
        return result

    @tool
    def replace_text(path: str, old_string: str, new_string: str) -> str:
        """Replaces exact old_string with new_string in a file. Best for surgical edits to avoid rewriting large files. Fails if old_string is not an exact match."""
        _log(f"    [TOOL] replace_text: {path!r}")
        if no_write:
            return f"DRY-RUN: would replace string in {path}"
        try:
            p = Path(path)
            if not p.is_absolute():
                p = REPO_ROOT / p
            if not p.exists():
                return f"ERROR: file not found: {p}"
            content = p.read_text(encoding="utf-8")
            if old_string not in content:
                return "ERROR: old_string not found exactly in the file. Read the file to get the exact literal string."
            content = content.replace(old_string, new_string, 1)
            p.write_text(content, encoding="utf-8")
            return f"OK: Replaced text in {p.relative_to(REPO_ROOT)}"
        except Exception as e:
            return f"ERROR: {e!r}"

    tools = [bash, read_file, write_file, replace_text]

    # Initialize Executor Model (Ollama)
    # Note: ChatOllama handles the API base URL natively
    ollama_base = executor_url.replace("/v1", "") if executor_url.endswith("/v1") else executor_url
    executor_model = ChatOllama(
        model=executor_model_name,
        temperature=0,
        base_url=ollama_base
    ).bind_tools(tools)

    def planner_node(state: WorkerState):
        """NIM Brain plans the next step or updates order.txt if a step is done."""
        current_key = next(key_iterator)
        planner_model = ChatNVIDIA(
            model=planner_model_name,
            api_key=current_key,
            temperature=0.1,
            base_url=planner_url
        )

        _log("--- NIM BRAIN (PLANNER) ---")
        
        sys_msg = SystemMessage(content=(
            "You are the BRAIN orchestrator for the Surf Health project.\n"
            "Review the current order.txt and the recent execution history.\n\n"
            "INSTRUCTIONS:\n"
            "1. If the current highest-priority task is NOT COMPLETE: Output a concise plan for the local executor to follow. Do NOT output <UPDATED_ORDER>.\n"
            "2. If the executor has successfully completed the task: Output a fully updated order.txt enclosed EXACTLY in <UPDATED_ORDER>...</UPDATED_ORDER> tags. Mark the item complete [✅].\n"
            "3. If the entire order.txt is DONE, output <UPDATED_ORDER> with STATUS: DONE.\n"
            "Do not execute tools yourself. You must rely on the executor."
        ))

        user_msg = HumanMessage(content=f"Current order.txt:\n\n{state['order_text']}")
        
        # We only pass the system prompt, the order.txt, and the messages from the executor
        # We keep the context lean by letting the graph reset messages after an order update.
        prompt = [sys_msg, user_msg] + state["messages"]

        t0 = time.time()
        response = planner_model.invoke(prompt)
        wall = time.time() - t0
        
        # Calculate cost
        cost = _tokens_cost(response.response_metadata, planner_model_name)
        _log(f"  [NIM] wall={wall:.1f}s | cost=${cost:.4f}")

        content = response.content
        m = re.search(r"<UPDATED_ORDER>(.*?)</UPDATED_ORDER>", content, re.DOTALL)
        
        if m:
            updated_order = m.group(1).strip()
            _log(f"  [NIM] Produced <UPDATED_ORDER>")
            return {"updated_order": updated_order, "current_plan": "DONE", "total_cost": cost}
        else:
            _log(f"  [NIM] Produced new plan: {content[:100]}...")
            return {"current_plan": content, "total_cost": cost}

    def executor_node(state: WorkerState):
        """Ollama executes the plan using tools."""
        _log("--- OLLAMA EXECUTOR ---")
        sys_msg = SystemMessage(content=(
            f"You are the EXECUTOR. Strictly follow this plan using your tools:\n\n{state['current_plan']}\n\n"
            "If a step fails, try to diagnose it. When finished with the plan steps, summarize what you did and the results."
        ))
        
        # For Ollama, we only feed it the current plan and its own recent tool interactions
        prompt = [sys_msg] + state["messages"]
        
        t0 = time.time()
        response = executor_model.invoke(prompt)
        wall = time.time() - t0
        
        cost = _tokens_cost(response.response_metadata if hasattr(response, 'response_metadata') else {}, executor_model_name)
        _log(f"  [OLLAMA] wall={wall:.1f}s")
        
        return {"messages": [response], "total_cost": cost}

    tool_executor = ToolNode(tools)

    def should_continue(state: WorkerState) -> Literal["tools", "planner", "__end__"]:
        if state.get("current_plan") == "DONE" or state.get("updated_order"):
            return "__end__"
            
        last_message = state["messages"][-1] if state["messages"] else None
        if last_message and hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
            
        return "planner"

    workflow = StateGraph(WorkerState)
    workflow.add_node("planner", planner_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("tools", tool_executor)

    workflow.add_edge(START, "planner")
    workflow.add_edge("planner", "executor")
    
    workflow.add_conditional_edges(
        "executor",
        should_continue,
        {
            "tools": "tools",
            "planner": "planner",
            "__end__": END
        }
    )
    workflow.add_edge("tools", "executor")

    app = workflow.compile()

    iters = 0
    total_spend = 0.0

    while True:
        if max_iters and iters >= max_iters:
            _log(f"Reached --max-iters={max_iters}, exiting")
            break
        iters += 1

        order_text = _read_order()
        if _is_done(order_text):
            _log("order.txt has STATUS: DONE — exiting")
            break

        _log(f"--- hybrid iter {iters} ---")

        # Initial state for this iteration resets the `messages` array
        # This prevents the context window from growing infinitely
        initial_state = {
            "order_text": order_text,
            "messages": [],
            "current_plan": "",
            "updated_order": "",
            "task_done": False,
            "total_cost": 0.0
        }

        # Run the graph for one full task cycle
        # We limit the recursion to prevent runaway tool loops within a single task
        final_state = None
        try:
            for event in app.stream(initial_state, {"recursion_limit": executor_rounds * 2 + 5}):
                for node_name, node_state in event.items():
                    if "total_cost" in node_state:
                        total_spend += node_state["total_cost"]
                final_state = event
        except Exception as e:
            _log(f"LangGraph execution error: {e!r}")
            time.sleep(sleep_s)
            continue

        if budget_usd > 0 and total_spend >= budget_usd:
            _log(f"Budget ${budget_usd:.2f} reached (${total_spend:.4f}), exiting")
            break

        # Extract the final state from the last event
        if final_state and "__end__" not in final_state:
            # Look inside the last node's state
            last_node = list(final_state.values())[0]
            updated_order = last_node.get("updated_order")
        else:
            updated_order = None

        if updated_order and not no_write:
            if updated_order.strip() == order_text.strip():
                _log("  order.txt unchanged this iteration")
            else:
                backup = _write_order(updated_order)
                _log(f"  order.txt updated; prior backed up to {backup.relative_to(REPO_ROOT)}")
        elif not updated_order:
            _log("  WARN: no updated order from NIM; order.txt left untouched. The executor might have failed or hit recursion limit.")

        time.sleep(sleep_s)

    _log(f"hybrid done | iters={iters} | total cost=${total_spend:.4f}")
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
            planner_model_name=planner_model,
            executor_url=OLLAMA_BASE_URL,
            executor_model_name=executor_model,
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
