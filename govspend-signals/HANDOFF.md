# govspend-signals — Handoff

> Last updated: 2026-05-10

## What This Is

A fully automated government-spending investment signal box. It monitors 10 public data sources for signals that precede equity moves, stores them in SQLite, sends alerts via Telegram/SMTP/webhook, and generates a morning digest every day at 6:30 AM.

**Investment thesis:** Non-defense, non-fossil-fuel equities that benefit from federal spending. Four sectors: government healthcare/managed care, regulated utilities, civil infrastructure, government IT/services.

## Quick Start (10 minutes)

```bash
# 1. Clone and install
cd govspend-signals
python3 -m venv .venv
.venv/bin/pip install -e ".[full]"    # rich + rapidfuzz + yfinance + httpx

# 2. Set required env var (SEC blocks unidentified clients)
export EDGAR_USER_AGENT="Your Name your@email.com"

# 3. Copy config and init DB
cp config.example.toml config.toml
.venv/bin/govspend init

# 4. Run first ingest (30-60s, all sources)
.venv/bin/govspend ingest

# 5. Open the dashboard
.venv/bin/govspend dashboard

# 6. Set up cron (6:30 AM weekdays)
crontab -e
# Add: 30 6 * * 1-5 /absolute/path/to/scripts/run_morning.sh >> /absolute/path/to/logs/morning.log 2>&1
```

## API Keys (optional but recommended)

| Key | Purpose | Where to get |
|-----|---------|--------------|
| `EDGAR_USER_AGENT` | **REQUIRED** — SEC blocks unidentified clients | Set to "Name email@domain.com" |
| `TELEGRAM_BOT_TOKEN` | Morning digest via Telegram | @BotFather → /newbot |
| `TELEGRAM_CHAT_ID` | Your chat ID | Send msg to bot, call GET /getUpdates |
| `SMTP_PASSWORD` | Morning digest via email | Gmail App Password (2FA required) |
| `PROPUBLICA_API_KEY` | Higher rate limit for Congress API | propublica.org/datastore |
| `LOBBYING_API_KEY` | Higher rate limit for Senate LDA API | lda.senate.gov/api |

Put all keys in `.env` in the repo root — `run_morning.sh` loads it automatically.

## Commands

```bash
govspend ingest                          # run all 10 ingestors
govspend ingest --source usaspending     # run one source
govspend poll                            # EDGAR-only poll
govspend watch                           # EDGAR continuous polling
govspend watch-ingest                    # all ingestors on a loop

govspend dashboard                       # live Rich terminal dashboard
govspend dashboard --no-live             # one-shot snapshot
govspend digest                          # print morning digest
govspend digest --telegram --email       # send via Telegram + email
govspend signals --hours 48 --source usaspending
govspend signals --ticker UNH --json     # JSON output for scripting

govspend sector-rotation                 # which sectors are hot (24h vs 7d)
govspend options                         # options plays around upcoming catalysts
govspend basket                          # ethical-screen portfolio allocation
govspend price-history                   # historical returns around catalyst dates
govspend price-history --ticker UNH

govspend export --hours 168 --out signals.csv
govspend status
govspend tickers update
govspend tickers lookup UNH
```

## Data Sources (all free public APIs)

| Source | What it captures | Lead time |
|--------|-----------------|-----------|
| `edgar` | SC 13D/13G activist stakes, 8-K material events, Form 4 insider buys | Real-time |
| `usaspending` | Federal contracts ≥$1M by agency | Days–weeks |
| `fedregister` | CMS/EPA/DOT/FERC rules and notices | Days–weeks |
| `congress` | Congressional STOCK Act trade disclosures | 45–90 days |
| `sbir` | SBIR/STTR grant awards (with 💥 small-cap explosion flag) | Weeks |
| `norway` | Norges Bank Investment Management 13F filings | Quarterly |
| `catalyst` | CMS rate notices, FOMC meetings, fiscal year-end | Static calendar |
| `grants_gov` | Notices of Funding Opportunity (NOFOs) | 3–12 months |
| `propublica` | Congressional bills across 6 sectors | 3–18 months |
| `lobbying` | Senate LDA quarterly lobbying disclosures | Leading indicator |

## File Structure

```
govspend-signals/
├── config.example.toml          # copy to config.toml and edit
├── govspend_signals/
│   ├── cli.py                   # all subcommands
│   ├── config.py                # Config dataclass + loader
│   ├── storage.py               # SQLite store
│   ├── signal.py                # unified Signal dataclass
│   ├── edgar.py                 # EDGAR client + rate limiter
│   ├── poller.py                # EDGAR poll_once()
│   ├── resolver.py              # subsidiary→ticker resolver (the moat)
│   ├── digest.py                # morning digest generator
│   ├── dashboard.py             # Rich terminal dashboard
│   ├── price_context.py         # yfinance catalyst reaction analyser
│   ├── sector_rotation.py       # government money flow velocity
│   ├── options_strategy.py      # catalyst-driven options plays
│   ├── basket.py                # ethical screen basket builder
│   ├── notifier.py              # base notifier classes
│   ├── ingestors/               # 10 data source ingestors
│   └── notifiers/               # telegram, webhook, smtp
├── tests/                       # 397+ tests, all passing
├── scripts/
│   ├── run_morning.sh           # cron-ready morning pipeline (5 steps)
│   ├── setup.sh                 # first-time setup script
│   └── com.frankramblings.govspend.plist  # macOS launchd template
└── docs/superpowers/plans/      # implementation plans
```

## Resolver (the moat)

`resolver.py` maps contract recipient names to tickers. When the government awards "$5M to Centene Federal Services LLC", the resolver maps that to CNC. It has 150+ curated entries, fuzzy matching, and EDGAR company search fallback.

To add new mappings: edit `SUBSIDIARY_MAP` in `resolver.py`. Keys are uppercase, legal suffixes stripped.

## Investment Commands in Detail

### `govspend sector-rotation`
Shows which sectors are receiving the most signal activity in the last 24h compared to the 7-day baseline. Use this to spot where government money is accelerating.

```
govspend sector-rotation --hours 24 --compare-hours 168
```

### `govspend options`
Generates catalyst-driven options plays. Reads upcoming events from the catalyst ingestor and matches them to sector thesis:
- CMS rate notices → BUY CALL on managed care (UNH, ELV, CNC)
- FOMC meetings → BUY PUT on regulated utilities (NEE, DUK, SO)
- Infrastructure spending → BUY CALL on contractors (PWR, MTZ, J)

Requires `pip install yfinance` for live strike lookup; falls back gracefully.

```
govspend options --ticker UNH --days-before 7
```

### `govspend basket`
Builds an ethical-screen portfolio weighted by trailing government contract dollars. Automatically excludes defense contractors (LMT, RTX, NOC, GD, BA...) and fossil fuel companies (XOM, CVX, COP...).

```
govspend basket --hours 720 --min-weight 1.0
govspend basket --equal-weight
```

## Extending

**Add a new ingestor:**
1. Create `govspend_signals/ingestors/my_source.py` with `def ingest(...) -> list[Signal]`
2. Add it to `_run_ingestors()` in `cli.py`
3. Add it to `_ALL_SOURCES` in `digest.py` and `_SOURCE_LABELS`
4. Add config section to `config.py` and `config.example.toml`
5. Write tests in `tests/ingestors/test_my_source.py`

**Add a new notifier:**
1. Create `govspend_signals/notifiers/my_notifier.py` implementing `emit(signal)` and `emit_digest(text)`
2. Wire into `_build_signal_notifier()` in `cli.py`

## macOS launchd (automated scheduling)

```bash
# Edit the plist with your absolute paths:
nano scripts/com.frankramblings.govspend.plist

# Install:
cp scripts/com.frankramblings.govspend.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.frankramblings.govspend.plist
```

This runs `run_morning.sh` at 6:30 AM Monday–Friday.
