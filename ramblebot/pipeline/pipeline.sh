#!/usr/bin/env bash
# RambleBot nightly pipeline: sweep → ingest → embed
# Uses a lockfile to prevent overlapping runs.
set -euo pipefail

RAMBLEBOT_HOME="${RAMBLEBOT_HOME:-$HOME/ramblebot}"
LOCK="$RAMBLEBOT_HOME/.pipeline.lock"
LOG="$RAMBLEBOT_HOME/logs/pipeline.log"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$RAMBLEBOT_HOME/logs"

# Acquire lock — mkdir is atomic on local filesystems (portable, works on macOS)
LOCKDIR="${LOCK}.d"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "$(date -u +%FT%TZ) pipeline already running, skipping" >> "$LOG"
  exit 0
fi
trap 'rm -rf "$LOCKDIR"' EXIT

echo "$(date -u +%FT%TZ) pipeline starting" >> "$LOG"

# Sweep
bash "$SCRIPT_DIR/../sweep.sh" "$RAMBLEBOT_HOME/archive" >> "$LOG" 2>&1

# Ingest
cd "$SCRIPT_DIR/.."
python3 -m pipeline.ingest >> "$LOG" 2>&1

# Embed
python3 -m pipeline.embed >> "$LOG" 2>&1

echo "$(date -u +%FT%TZ) pipeline complete" >> "$LOG"
