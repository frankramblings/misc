#!/usr/bin/env bash
# RambleBot transcript sweep.
#
# Pulls Claude Code conversation JSONL files (and supporting config) from each
# Tailscale host into a single archive directory, keyed by host so provenance
# is preserved for downstream extraction.
#
# Usage:
#   ramblebot/sweep.sh [archive-dir]
#
# Defaults to ~/ramblebot/archive. Assumes Tailscale SSH (or your own ssh
# config) lets you connect to each host without a password prompt.

set -euo pipefail

DEST="${1:-$HOME/ramblebot/archive}"

HOSTS=(
  "endor.bicolor-triceratops.ts.net"        # Ubuntu
  "bespin.bicolor-triceratops.ts.net"       # Mac Mini
  "wis-a422.bicolor-triceratops.ts.net"     # MacBook Pro
)

mkdir -p "$DEST"

for host in "${HOSTS[@]}"; do
  short="${host%%.*}"
  echo "==> $short ($host)"

  if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" true 2>/dev/null; then
    echo "    skipped: cannot reach $host over ssh"
    continue
  fi

  mkdir -p "$DEST/$short"

  # Pull .claude/ — projects/*.jsonl is the actual transcript corpus,
  # .claude.json gives us the project-path lookup table, settings*.json
  # captures any per-host config that shaped the conversations.
  rsync -avh --prune-empty-dirs \
    --include='*/' \
    --include='*.jsonl' \
    --include='.claude.json' \
    --include='settings.json' \
    --include='settings.local.json' \
    --exclude='*' \
    "$host:.claude/" "$DEST/$short/dot-claude/"

  # .claude.json lives one level up; rsync above won't catch it.
  rsync -avh --ignore-missing-args "$host:.claude.json" "$DEST/$short/.claude.json" 2>/dev/null || true
done

echo
echo "Archive: $DEST"
find "$DEST" -name '*.jsonl' | wc -l | awk '{print $1 " transcript files collected"}'
