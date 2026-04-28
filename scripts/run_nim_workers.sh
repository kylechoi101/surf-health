#!/usr/bin/env bash
# Start / stop the NIM/Ollama worker that continues order.txt when Claude is out of tokens.
#
# Usage:
#   scripts/run_nim_workers.sh                              # NIM foreground
#   scripts/run_nim_workers.sh fg [args...]                 # foreground (explicit)
#   scripts/run_nim_workers.sh bg [args...]                 # background, pid -> nim_worker.pid
#   scripts/run_nim_workers.sh stop                         # kill the background worker
#   scripts/run_nim_workers.sh status                       # show pid + last log lines
#
#   # Local Ollama (gemma4:31b, no API key needed)
#   scripts/run_nim_workers.sh fg --backend ollama --max-iters 3
#
#   # NIM cloud with budget cap + dry-run
#   scripts/run_nim_workers.sh fg --max-iters 5 --budget-usd 2.00 --no-write
#
#   # Delete orphan dead code (small, safe test task)
#   scripts/run_nim_workers.sh fg --backend ollama --max-iters 2 \
#     --max-bash-failures 3 --budget-usd 0
#
# All extra args are forwarded to nim_worker.py.
# Loads NVIDIA_API_KEYS from backend/.env if not already set in the environment.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"
PID_FILE="$ROOT/nim_worker.pid"
LOG_FILE="$ROOT/nim_worker.log"

if [[ -z "${NVIDIA_API_KEYS:-}" && -z "${NVIDIA_API_KEY:-}" ]]; then
  if [[ -f "$ROOT/backend/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/backend/.env"
    set +a
  fi
fi

cmd="${1:-fg}"
case "$cmd" in
  bg)
    shift
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "already running: pid $(cat "$PID_FILE")" >&2
      exit 1
    fi
    nohup "$PY" "$ROOT/scripts/nim_worker.py" "$@" >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "started in background, pid $(cat "$PID_FILE")"
    echo "log: $LOG_FILE"
    ;;
  stop)
    if [[ -f "$PID_FILE" ]]; then
      pid="$(cat "$PID_FILE")"
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        echo "stopped pid $pid"
      else
        echo "pid $pid not running"
      fi
      rm -f "$PID_FILE"
    else
      echo "no pid file at $PID_FILE"
    fi
    ;;
  status)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "running: pid $(cat "$PID_FILE")"
    else
      echo "not running"
    fi
    [[ -f "$LOG_FILE" ]] && tail -20 "$LOG_FILE"
    ;;
  fg)
    shift
    exec "$PY" "$ROOT/scripts/nim_worker.py" "$@"
    ;;
  hybrid)
    shift
    # NIM brain + Ollama executor. Default budget 0.50; pass extra args through.
    exec "$PY" "$ROOT/scripts/nim_worker.py" \
      --mode hybrid \
      --executor-model "gemma4:31b" \
      --budget-usd 0.50 \
      "$@"
    ;;
  *)
    exec "$PY" "$ROOT/scripts/nim_worker.py" "$@"
    ;;
esac
