#!/usr/bin/env bash
# RambleBot nightly pipeline: sweep → ingest → embed
# Uses a lockfile to prevent overlapping runs.
set -euo pipefail

RAMBLEBOT_HOME="${RAMBLEBOT_HOME:-$HOME/ramblebot}"
LOCK="$RAMBLEBOT_HOME/.pipeline.lock"
LOG="$RAMBLEBOT_HOME/logs/pipeline.log"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$RAMBLEBOT_HOME/logs"

# Acquire lock
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date -u +%FT%TZ) pipeline already running, skipping" >> "$LOG"
  exit 0
fi
trap 'flock -u 9; rm -f "$LOCK"' EXIT

echo "$(date -u +%FT%TZ) pipeline starting" >> "$LOG"

# Sweep
bash "$SCRIPT_DIR/../sweep.sh" "$RAMBLEBOT_HOME/archive" >> "$LOG" 2>&1

# Ingest
cd "$SCRIPT_DIR"
python -m pipeline.ingest >> "$LOG" 2>&1

# Embed
python -m pipeline.embed >> "$LOG" 2>&1

echo "$(date -u +%FT%TZ) pipeline complete" >> "$LOG"
