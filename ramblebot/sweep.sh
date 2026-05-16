#!/usr/bin/env bash
# RambleBot transcript sweep.
#
# For each tailnet host: discover every .claude/ that actually holds
# transcripts (i.e. has a projects/ subdir), then rsync only the JSONLs and
# the config files that give them context, into a central archive that
# preserves the original full source path so nothing collides.
#
# Reasonably thorough, not exhaustive:
#   - macOS hosts get a Spotlight (mdfind) lookup — indexed, near-instant.
#   - All hosts also get a bounded `find` over user-writable roots
#     (/Users /home /root /opt /srv) with prunes for the usual noise
#     (Caches, Containers, CloudStorage, node_modules, Time Machine bundles,
#     .Trash, .git) and a per-host wall-clock timeout.
#   - Only directories containing projects/ survive the filter, so we
#     skip per-repo .claude/ config dirs that have no transcripts.
#
# Usage:
#   ramblebot/sweep.sh [archive-dir]

set -euo pipefail

DEST="${1:-$HOME/ramblebot/archive}"
DISCOVERY_TIMEOUT="${DISCOVERY_TIMEOUT:-120}"   # seconds, per host

HOSTS=(
  "frank@endor.bicolor-triceratops.ts.net"        # Ubuntu
  "admin@bespin.bicolor-triceratops.ts.net"       # Mac Mini
  "wis-a422.bicolor-triceratops.ts.net"           # MacBook Pro (local user)
)

mkdir -p "$DEST"

for host in "${HOSTS[@]}"; do
  hostpart="${host#*@}"
  short="${hostpart%%.*}"
  echo "==> $short ($host)"

  if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" true 2>/dev/null; then
    echo "    skipped: cannot reach $host over ssh"
    continue
  fi

  echo "    discovering .claude directories..."
  paths=()
  while IFS= read -r line; do
    [ -n "$line" ] && paths+=("$line")
  done < <(ssh "$host" "DISCOVERY_TIMEOUT=$DISCOVERY_TIMEOUT bash -s" <<'REMOTE'
set -u
TIMEOUT="${DISCOVERY_TIMEOUT:-120}"
collect=""

# macOS: indexed Spotlight lookup. Exact-name match avoids substring hits.
if command -v mdfind >/dev/null 2>&1; then
  collect="$collect
$(mdfind "kMDItemFSName == '.claude'" 2>/dev/null)"
fi

# Filesystem walk over user-writable roots, pruning the usual noise.
collect="$collect
$(timeout "$TIMEOUT" find /Users /home /root /opt /srv 2>/dev/null \
  -path '*/Library/Caches' -prune -o \
  -path '*/Library/Containers' -prune -o \
  -path '*/Library/Mobile Documents' -prune -o \
  -path '*/Library/CloudStorage' -prune -o \
  -path '*/node_modules' -prune -o \
  -path '*/.Trash*' -prune -o \
  -path '*/.git' -prune -o \
  -path '*/Backups.backupdb' -prune -o \
  -path '*/.TimeMachine.localsnapshots' -prune -o \
  -type d -name .claude -print 2>/dev/null)"

# Keep only directories that hold real transcript stores.
printf "%s\n" "$collect" | awk 'NF' | sort -u | while IFS= read -r d; do
  [ -d "$d/projects" ] && echo "$d"
done
REMOTE
)

  if [ ${#paths[@]} -eq 0 ]; then
    echo "    no .claude/projects directories found"
    continue
  fi

  echo "    found ${#paths[@]}:"
  for p in "${paths[@]}"; do echo "      $p"; done

  mkdir -p "$DEST/$short"
  for path in "${paths[@]}"; do
    # -R preserves the full source path under the destination, so
    # /Users/frank/.claude lands at archive/bespin/Users/frank/.claude
    # and discoveries from different roots can't overwrite each other.
    rsync -avhR --prune-empty-dirs \
      --include='*/' \
      --include='*.jsonl' \
      --include='.claude.json' \
      --include='settings.json' \
      --include='settings.local.json' \
      --exclude='*' \
      "$host:$path/" "$DEST/$short/"
  done
done

echo
echo "Archive: $DEST"
find "$DEST" -name '*.jsonl' 2>/dev/null | wc -l | awk '{print $1 " transcript files collected"}'
