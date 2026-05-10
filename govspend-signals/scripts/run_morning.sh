#!/usr/bin/env bash
# run_morning.sh — morning pipeline for govspend-signals
#
# Usage:
#   ./scripts/run_morning.sh
#
# Environment variables (set in .env or export before running):
#   EDGAR_USER_AGENT   — required, e.g. "Your Name your@email.com"
#   TELEGRAM_BOT_TOKEN — optional, enables Telegram delivery
#   TELEGRAM_CHAT_ID   — optional
#   SMTP_PASSWORD      — optional, enables email delivery
#
# Cron example (run at 6:30 AM every weekday):
#   30 6 * * 1-5 /path/to/govspend-signals/scripts/run_morning.sh >> /path/to/govspend-signals/logs/morning.log 2>&1

set -euo pipefail

# ── Resolve paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
VENV="$REPO_ROOT/.venv"
GOVSPEND="$VENV/bin/govspend"
LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"

# ── Load .env if present ───────────────────────────────────────────────────────
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$REPO_ROOT/.env"
  set +a
fi

# ── Validate ───────────────────────────────────────────────────────────────────
if [[ -z "${EDGAR_USER_AGENT:-}" ]]; then
  echo "[run_morning] ERROR: EDGAR_USER_AGENT is not set. Aborting." >&2
  exit 1
fi

cd "$REPO_ROOT"

echo ""
echo "═══════════════════════════════════════════════════════"
echo " govspend-signals morning run — $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════"

# ── Step 1: EDGAR — poll for new filings ──────────────────────────────────────
echo "[1/4] Polling SEC EDGAR for new filings..."
"$GOVSPEND" poll || echo "[WARNING] EDGAR poll returned non-zero"

# ── Step 2: All other ingestors ───────────────────────────────────────────────
echo "[2/4] Running all ingestors (USASpending, Federal Register, Congress, SBIR, Norway, Catalyst)..."
"$GOVSPEND" ingest || echo "[WARNING] ingest returned non-zero"

# ── Step 3: Morning digest ────────────────────────────────────────────────────
echo "[3/4] Generating morning digest..."
HTML_OUT="$LOG_DIR/digest_$(date '+%Y-%m-%d').html"
DIGEST_ARGS="--hours 24 --html-out $HTML_OUT"

if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  DIGEST_ARGS="$DIGEST_ARGS --telegram"
fi
if [[ -n "${SMTP_PASSWORD:-}" ]]; then
  DIGEST_ARGS="$DIGEST_ARGS --email"
fi

"$GOVSPEND" digest $DIGEST_ARGS

# ── Step 4: Status summary ────────────────────────────────────────────────────
echo "[4/4] Status:"
"$GOVSPEND" status

echo ""
echo "═══════════════════════════════════════════════════════"
echo " Done — $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════"
