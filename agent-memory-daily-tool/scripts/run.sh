#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 -m src.run_daily --config config/config.json "$@"
