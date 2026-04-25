#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT_DIR/storage/server.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "No pid file found, server may not be running."
  exit 0
fi

PID="$(cat "$PID_FILE")"
if [[ -z "${PID:-}" ]]; then
  echo "Pid file is empty, cleaning up."
  rm -f "$PID_FILE"
  exit 0
fi

if ! kill -0 "$PID" 2>/dev/null; then
  echo "Process not running, cleaning up stale pid file."
  rm -f "$PID_FILE"
  exit 0
fi

kill "$PID" 2>/dev/null || true

for _ in {1..10}; do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "Server stopped, pid=$PID"
    exit 0
  fi
  sleep 1
done

echo "Graceful stop timeout, force killing pid=$PID"
kill -9 "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
echo "Server force stopped."
