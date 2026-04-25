#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
PID_FILE="$ROOT_DIR/storage/server.pid"
LOG_FILE="$ROOT_DIR/storage/server.log"
CONFIG_FILE="$ROOT_DIR/config.toml"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python not found: $PYTHON_BIN"
  echo "Please create venv first: python -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

mkdir -p "$ROOT_DIR/storage"

LISTEN_PORT="$("$PYTHON_BIN" - <<'PY'
import toml
from pathlib import Path
cfg = toml.load(Path("config.toml"))
print(cfg.get("listen_port", 8080))
PY
)"

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE")"
  if [[ -n "${OLD_PID:-}" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Server already running, pid=$OLD_PID"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if lsof -nP -iTCP:"$LISTEN_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $LISTEN_PORT is already in use, aborting start."
  echo "Please run ./scripts/stop.sh first or free the port manually."
  exit 1
fi

cd "$ROOT_DIR"

# 默认不清理代理；如需强制清理，可用:
# MPT_UNSET_PROXY=1 ./scripts/start.sh
if [[ "${MPT_UNSET_PROXY:-0}" == "1" ]]; then
  unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
  unset SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy
fi

nohup "$PYTHON_BIN" main.py >>"$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" >"$PID_FILE"

sleep 1
if kill -0 "$NEW_PID" 2>/dev/null; then
  if lsof -nP -iTCP:"$LISTEN_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Server started successfully, pid=$NEW_PID, port=$LISTEN_PORT"
    echo "Log file: $LOG_FILE"
  else
    echo "Server process exists but port $LISTEN_PORT is not listening yet."
    echo "Check log file: $LOG_FILE"
    exit 1
  fi
else
  echo "Server failed to start, check log: $LOG_FILE"
  rm -f "$PID_FILE"
  exit 1
fi
