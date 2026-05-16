#!/usr/bin/env bash
# RambleBot transcript sweep.
#
# For each tailnet host: discover every .claude/ that actually holds
# transcripts (i.e. has a projects/ subdir), then rsync only the JSONLs and
# the config files that give them context, into a central archive that
# preserves the original full source path so nothing collides.
#
# Reasonably thorough, not exhaustive:
#   - macOS hosts get a Spotlight (mdfind) lookup as a supplemental signal.
#   - All hosts also get a `find` over user-writable roots
#     (/Users /home /root /opt /srv) with prunes for the usual noise
#     (Caches, Containers, CloudStorage, node_modules, Time Machine bundles,
#     .Trash, .git). Wrapped in a wall-clock timeout when one is available.
#   - Only directories containing projects/ survive the filter, so per-repo
#     .claude/ config dirs without transcripts get skipped.
#
# The host whose short name matches the local hostname is handled without
# SSH — useful when Remote Login is off on the central machine.
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

discovery_script() {
cat <<'REMOTE'
set -u
TIMEOUT="${DISCOVERY_TIMEOUT:-120}"

# `timeout` is GNU coreutils; not on stock macOS. Try common names,
# else run without the wrapper.
TO=""
if command -v timeout >/dev/null 2>&1; then
  TO="timeout $TIMEOUT"
elif command -v gtimeout >/dev/null 2>&1; then
  TO="gtimeout $TIMEOUT"
fi

collect=""

# Spotlight (macOS) — supplemental. Hidden dirs aren't always indexed.
if command -v mdfind >/dev/null 2>&1; then
  collect="$collect
$(mdfind "kMDItemFSName == '.claude'" 2>/dev/null)"
fi

# Filesystem walk over user-writable roots.
collect="$collect
$($TO find /Users /home /root /opt /srv 2>/dev/null \
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

printf "%s\n" "$collect" | awk 'NF' | sort -u | while IFS= read -r d; do
  [ -d "$d/projects" ] && echo "$d"
done
REMOTE
}

mkdir -p "$DEST"
LOCAL_SHORT="$(hostname -s 2>/dev/null || true)"

for host in "${HOSTS[@]}"; do
  hostpart="${host#*@}"
  short="${hostpart%%.*}"
  echo "==> $short ($host)"

  is_local=0
  if [ "$short" = "$LOCAL_SHORT" ]; then
    is_local=1
    echo "    running locally (this is $short)"
  elif ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" true 2>/dev/null; then
    echo "    skipped: cannot reach $host over ssh"
    continue
  fi

  echo "    discovering .claude directories..."
  paths=()
  while IFS= read -r line; do
    [ -n "$line" ] && paths+=("$line")
  done < <(
    if [ "$is_local" -eq 1 ]; then
      DISCOVERY_TIMEOUT="$DISCOVERY_TIMEOUT" bash -c "$(discovery_script)"
    else
      ssh "$host" "DISCOVERY_TIMEOUT=$DISCOVERY_TIMEOUT bash -s" <<< "$(discovery_script)"
    fi
  )

  if [ ${#paths[@]} -eq 0 ]; then
    echo "    no .claude/projects directories found"
    continue
  fi

  echo "    found ${#paths[@]}:"
  for p in "${paths[@]}"; do echo "      $p"; done

  mkdir -p "$DEST/$short"
  for path in "${paths[@]}"; do
    if [ "$is_local" -eq 1 ]; then
      src="$path/"
    else
      src="$host:$path/"
    fi
    # -R preserves the full source path under the destination, so
    # /Users/admin/.claude lands at archive/bespin/Users/admin/.claude
    # and discoveries from different roots can't overwrite each other.
    rsync -avhR --prune-empty-dirs \
      --include='*/' \
      --include='*.jsonl' \
      --include='.claude.json' \
      --include='settings.json' \
      --include='settings.local.json' \
      --exclude='*' \
      "$src" "$DEST/$short/"
  done
done

echo
echo "Archive: $DEST"
find "$DEST" -name '*.jsonl' 2>/dev/null | wc -l | awk '{print $1 " transcript files collected"}'
