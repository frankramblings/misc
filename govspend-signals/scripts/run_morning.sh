#!/usr/bin/env bash
# run_morning.sh — complete morning pipeline for govspend-signals
#
# Usage:
#   ./scripts/run_morning.sh
#
# Environment variables (set in .env or export before running):
#   EDGAR_USER_AGENT     — REQUIRED: "Your Name your@email.com"
#   TELEGRAM_BOT_TOKEN   — optional: enables Telegram digest delivery
#   TELEGRAM_CHAT_ID     — optional
#   SMTP_PASSWORD        — optional: enables email digest delivery
#   PROPUBLICA_API_KEY   — optional: higher rate limits for Congress API
#   LOBBYING_API_KEY     — optional: higher rate limits for Senate LDA API
#
# Cron (6:30 AM weekdays):
#   30 6 * * 1-5 /path/to/run_morning.sh >> /path/to/logs/morning.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
VENV="$REPO_ROOT/.venv"
GOVSPEND="$VENV/bin/govspend"
LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"

if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$REPO_ROOT/.env"
  set +a
fi

if [[ -z "${EDGAR_USER_AGENT:-}" ]]; then
  echo "[run_morning] ERROR: EDGAR_USER_AGENT is not set. Aborting." >&2
  exit 1
fi

cd "$REPO_ROOT"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " govspend-signals morning run — $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════════════"

# ── Step 1: EDGAR — poll for new insider/activist filings ─────────────────────
echo "[1/5] Polling SEC EDGAR for new filings (SC 13D, 8-K, Form 4)..."
"$GOVSPEND" poll || echo "[WARNING] EDGAR poll returned non-zero"

# ── Step 2: All other ingestors ───────────────────────────────────────────────
echo "[2/5] Running all ingestors..."
echo "       USASpending  Federal Register  Congress trades  SBIR grants"
echo "       Norway fund  Catalyst          Grants.gov NOFOs ProPublica bills"
echo "       Senate LDA lobbying"
"$GOVSPEND" ingest || echo "[WARNING] ingest returned non-zero"

# ── Step 3: Morning digest ────────────────────────────────────────────────────
echo "[3/5] Generating morning digest..."
HTML_OUT="$LOG_DIR/digest_$(date '+%Y-%m-%d').html"
DIGEST_ARGS="--hours 24 --html-out $HTML_OUT"

if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  DIGEST_ARGS="$DIGEST_ARGS --telegram"
fi
if [[ -n "${SMTP_PASSWORD:-}" ]]; then
  DIGEST_ARGS="$DIGEST_ARGS --email"
fi

"$GOVSPEND" digest $DIGEST_ARGS

# ── Step 4: Sector rotation snapshot ─────────────────────────────────────────
echo "[4/5] Sector rotation (last 24h vs last 7d):"
"$GOVSPEND" sector-rotation --hours 24 --compare-hours 168 || true

# ── Step 5: Status summary ────────────────────────────────────────────────────
echo "[5/5] Status:"
"$GOVSPEND" status

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " Done — $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════════════"
