#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -n "${HOME:-}" ]]; then
  export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
else
  export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
fi

mkdir -p logs runtime

POLL_SECONDS="${DAILY_REPORT_POLL_SECONDS:-600}"
LAST_RUN_FILE="runtime/daily_scheduler.last_run_date"

echo "[$(date -u --iso-8601=seconds)] scheduler_started root=$ROOT mode=poll poll_seconds=$POLL_SECONDS"

while true; do
  poll_info="$(python3 -m src.schedule --poll --last-run-file "$LAST_RUN_FILE")"
  action="$(printf '%s' "$poll_info" | awk -F '\t' '{print $1}')"
  run_beijing_date="$(printf '%s' "$poll_info" | awk -F '\t' '{print $2}')"

  if [[ "$action" != "run" ]]; then
    echo "[$(date -u --iso-8601=seconds)] poll_wait beijing_date=$run_beijing_date next_check_seconds=$POLL_SECONDS"
    sleep "$POLL_SECONDS"
    continue
  fi

  echo "[$(date -u --iso-8601=seconds)] daily_report_start trigger_beijing_date=$run_beijing_date"
  if ./scripts/run.sh --send >> logs/cron.log 2>&1; then
    printf '%s\n' "$run_beijing_date" > "$LAST_RUN_FILE"
    echo "[$(date -u --iso-8601=seconds)] daily_report_success"
  else
    exit_code=$?
    echo "[$(date -u --iso-8601=seconds)] daily_report_failed exit_code=$exit_code"
  fi

  sleep "$POLL_SECONDS"
done
