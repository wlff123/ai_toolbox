#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p logs runtime
PID_FILE="runtime/daily_scheduler.pid"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE")"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "daily scheduler already running: pid=$old_pid"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

setsid "$ROOT/scripts/daily_scheduler.sh" >> "$ROOT/logs/scheduler.log" 2>&1 < /dev/null &
pid=$!
echo "$pid" > "$PID_FILE"
echo "daily scheduler started: pid=$pid"
