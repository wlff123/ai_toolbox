#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/runtime/daily_scheduler.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "daily scheduler not running: missing pid file"
  exit 1
fi

pid="$(cat "$PID_FILE")"
if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
  echo "daily scheduler running: pid=$pid"
else
  echo "daily scheduler not running: stale pid=$pid"
  exit 1
fi
