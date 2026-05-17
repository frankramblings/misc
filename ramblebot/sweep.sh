#!/usr/bin/env bash
# RambleBot transcript sweep.
#
# For each tailnet host: discover every .claude/ that actually holds
# transcripts (has a projects/ subdir), then rsync only the JSONLs and the
# config files that give them context, into a central archive that
# preserves the original full source path so nothing collides.
#
# A host entry prefixed with `local:` is swept on this machine without
# SSH — useful when Remote Login is off on the central machine, and the
# correct setup whenever you run the sweep on one of the listed hosts.
#
# Usage:
#   ramblebot/sweep.sh [archive-dir]

set -euo pipefail

DEST="${1:-$HOME/ramblebot/archive}"
DISCOVERY_TIMEOUT="${DISCOVERY_TIMEOUT:-120}"   # seconds, per host

HOSTS=(
  "frank@endor.bicolor-triceratops.ts.net"        # Ubuntu
  "frankemanuele@wis-a422.bicolor-triceratops.ts.net"  # MacBook Pro
  "local:bespin"                                  # Mac Mini (this machine)
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

# Canonical location for the current user — instant, no walk needed.
[ -d "$HOME/.claude/projects" ] && collect="$collect
$HOME/.claude"

# openclaw transcripts
[ -d "$HOME/.openclaw/agents" ] && collect="$collect
$HOME/.openclaw"

# Spotlight (macOS) — supplemental. Hidden dirs aren't always indexed.
if command -v mdfind >/dev/null 2>&1; then
  collect="$collect
$(mdfind "kMDItemFSName == '.claude'" 2>/dev/null)"
fi

# Bounded filesystem walk over user-writable roots. Depth cap guarantees
# the walk terminates even without a `timeout` binary present.
collect="$collect
$($TO find /Users /home /root /opt /srv 2>/dev/null \
  -maxdepth 8 \
  -path '*/Library' -prune -o \
  -path '*/.Trash*' -prune -o \
  -path '*/.git' -prune -o \
  -path '*/node_modules' -prune -o \
  -path '*/Backups.backupdb' -prune -o \
  -path '*/.TimeMachine.localsnapshots' -prune -o \
  -path '*/homebrew' -prune -o \
  -path '*.photoslibrary' -prune -o \
  -path '*.musiclibrary' -prune -o \
  -path '*.app' -prune -o \
  -path '*.bundle' -prune -o \
  -path '*.framework' -prune -o \
  -type d -name .claude -print 2>/dev/null)"

printf "%s\n" "$collect" | awk 'NF' | sort -u | while IFS= read -r d; do
  case "$d" in
    */ramblebot/archive/*) continue ;;
  esac
  [ -d "$d/projects" ] && echo "$d"
done
REMOTE
}

mkdir -p "$DEST"

for host in "${HOSTS[@]}"; do
  if [[ "$host" == local:* ]]; then
    short="${host#local:}"
    is_local=1
    echo "==> $short (local)"
  else
    hostpart="${host#*@}"
    short="${hostpart%%.*}"
    is_local=0
    echo "==> $short ($host)"
    if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" true 2>/dev/null; then
      echo "    skipped: cannot reach $host over ssh"
      continue
    fi
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
      --include='*.trajectory.jsonl' \
      --include='*.trajectory-path.json' \
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
