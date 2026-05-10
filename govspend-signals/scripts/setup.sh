#!/usr/bin/env bash
# setup.sh — first-time setup for govspend-signals on macOS
#
# Usage:
#   cd govspend-signals
#   ./scripts/setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

echo ""
echo "═══════════════════════════════════════════════════════"
echo " govspend-signals — first-time setup"
echo "═══════════════════════════════════════════════════════"

# ── 1. Python version check ────────────────────────────────────────────────────
PYTHON=$(command -v python3.11 || command -v python3.12 || command -v python3.13 || command -v python3.14 || true)
if [[ -z "$PYTHON" ]]; then
  echo "ERROR: Python 3.11+ is required. Install it from https://python.org or via Homebrew:"
  echo "  brew install python@3.12"
  exit 1
fi
echo "[1/6] Found Python: $($PYTHON --version)"

# ── 2. Create virtual environment ─────────────────────────────────────────────
if [[ ! -d ".venv" ]]; then
  echo "[2/6] Creating virtual environment..."
  "$PYTHON" -m venv .venv
else
  echo "[2/6] Virtual environment already exists — skipping"
fi

GOVSPEND=".venv/bin/govspend"
PIP=".venv/bin/pip"

# ── 3. Install package ────────────────────────────────────────────────────────
echo "[3/6] Installing govspend-signals..."
"$PIP" install -e ".[dev]" -q

# ── 4. Scaffold config ────────────────────────────────────────────────────────
if [[ ! -f "config.toml" ]]; then
  echo "[4/6] Creating config.toml from template..."
  "$GOVSPEND" init
else
  echo "[4/6] config.toml already exists — skipping"
fi

# ── 5. Create .env template ───────────────────────────────────────────────────
if [[ ! -f ".env" ]]; then
  echo "[5/6] Creating .env template..."
  cat > .env <<'ENV'
# govspend-signals environment variables
# Required:
EDGAR_USER_AGENT="Your Full Name your_email@example.com"

# Optional — Telegram alerts:
# TELEGRAM_BOT_TOKEN="1234567890:ABCxyz..."
# TELEGRAM_CHAT_ID="-1001234567890"

# Optional — email digest:
# SMTP_PASSWORD="your_gmail_app_password"

# Optional — webhook:
# WEBHOOK_URL="https://hooks.example.com/govspend"
# WEBHOOK_SECRET="your_secret"
ENV
  echo "  → Created .env — EDIT IT before running. Set EDGAR_USER_AGENT at minimum."
else
  echo "[5/6] .env already exists — skipping"
fi

# ── 6. Run tests ──────────────────────────────────────────────────────────────
echo "[6/6] Running test suite..."
.venv/bin/pytest tests/ -q --tb=short

echo ""
echo "═══════════════════════════════════════════════════════"
echo " Setup complete!"
echo ""
echo " Next steps:"
echo "   1. Edit .env and set EDGAR_USER_AGENT"
echo "   2. Edit config.toml (optional — defaults are good)"
echo "   3. Seed the ticker map:"
echo "        source .env && .venv/bin/govspend tickers update"
echo "   4. Run a manual morning pipeline:"
echo "        source .env && ./scripts/run_morning.sh"
echo "   5. Schedule daily runs (macOS):"
echo "        Edit scripts/com.frankramblings.govspend.plist (set your EDGAR_USER_AGENT)"
echo "        cp scripts/com.frankramblings.govspend.plist ~/Library/LaunchAgents/"
echo "        launchctl load ~/Library/LaunchAgents/com.frankramblings.govspend.plist"
echo "═══════════════════════════════════════════════════════"
