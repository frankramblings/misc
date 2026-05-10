# govspend-signals — handoff

This file exists so a fresh local Claude Code session (with the `superpowers`
plugin installed) can pick up where the web session left off. It captures the
strategy context, the current repo state, and the prompt to start the next
session with.

The build plan itself is intentionally omitted — re-derive it with superpowers'
brainstorming + planning skills.

---

## Strategy context (the why)

The goal is a personal "command center" that turns publicly available
government-spending and big-buyer signals into actionable trades. Two surfaces:

1. **Slow-and-steady book** — long-bias positions in companies whose revenue
   tracks federal/state spending in non-defense, non-fossil-fuel sectors:
   government-backed healthcare (CMS-driven managed care), regulated utilities
   (incl. partially-green), civil infrastructure & environmental engineering,
   non-defense government IT/services.

2. **Tactical / windfall sleeve** — event-driven trades around known catalysts:
   activist 13D filings, insider Form 4 cluster buys, small-cap government
   grant/contract announcements (DARPA / ARPA-H / BARDA / SBIR), CMS rate
   notices, Federal Register rule changes, congressional trade disclosures,
   hyperscaler capex guidance, sovereign-wealth-fund (Norway, PIF, Temasek)
   disclosures, central bank gold purchases.

Execution context: solo retail trader. Robinhood is fine for the slow-and-steady
book; a real broker (Interactive Brokers / Tastytrade / Fidelity ATP) is better
for the tactical sleeve, especially with options for leverage on known
catalysts.

The "edge" is operating in **Tier 2** — faster than retail headline-readers,
slower than HFTs. Read primary documents (SEC filings, Federal Register, agency
press releases) the moment they're published and pre-stage trade playbooks for
recurring catalysts.

Honest constraints: short-term gains taxed as ordinary income; small-cap moves
have real slippage; discipline failures (overtrading, no stops) destroy the
edge faster than the data does. None of this is investment advice.

---

## Repo state (what's on disk)

Branch: `claude/gov-spending-investment-tool-4a4ct`
Project root: `govspend-signals/`

```
govspend-signals/
├── pyproject.toml             setuptools + console_script `govspend`
├── .env.example               EDGAR_USER_AGENT (required), DB / events paths
├── config.example.toml        poll interval, forms, watchlist (4 categories)
├── .gitignore
└── govspend_signals/
    ├── __init__.py
    ├── config.py              loads TOML + env, validates User-Agent
    ├── edgar.py               SEC client: rate-limited, retries on 429/503;
    │                          fetches company_tickers.json + per-CIK
    │                          submissions; Filing dataclass
    ├── storage.py             SQLite: filings_seen, ticker_map, meta
    ├── notifier.py            Protocol + StdoutNotifier, JsonlNotifier,
    │                          FanoutNotifier
    ├── poller.py              poll_once() — refreshes ticker map daily,
    │                          per-ticker scan, dedupes, emits new filings
    └── cli.py                 subcommands: init, poll, watch,
                               tickers update / lookup
```

### What works (by inspection — not yet exercised live)

- Config loads from `config.toml` and env, refuses to run without a real
  `EDGAR_USER_AGENT`.
- Storage schema initializes idempotently.
- EDGAR client honors SEC's 10 req/s cap (configured at 8) and required
  User-Agent.
- CLI entry point `govspend` is wired via `pyproject.toml`.

### What is NOT done yet

- **No tests written.** The original plan included `tests/test_storage.py` and
  `tests/test_edgar.py`; neither exists yet. `tests/` directory is also not
  created.
- **No live smoke run executed.** Nothing has hit SEC's servers from this code.
- **No `requests` install verified.** The dep is declared in `pyproject.toml`
  but `pip install -e .` has not been run in this environment.
- **No additional ingestors built.** The signal box only covers SEC EDGAR.
  USAspending, Federal Register, congressional trades, Norway fund, hyperscaler
  capex, central bank gold, catalyst calendar, etc. — all still unbuilt.
- **No aggregation / morning-digest layer.** A unified "what happened in the
  last 24h across all sources" view is unbuilt.
- **No alert delivery beyond stdout/JSONL.** Telegram / Pushover / email /
  webhook notifiers are unbuilt.

### Quick verification commands (run after `pip install -e .`)

```
cp config.example.toml config.toml
export EDGAR_USER_AGENT="Your Name your_email@example.com"
govspend tickers update         # seed SQLite ticker_map (~13k rows)
govspend tickers lookup UNH     # sanity check
govspend poll                   # one cycle against the watchlist
```

First `poll` run will dump up to 7 days of qualifying filings (per
`max_age_days` in config) for every watchlist ticker.

---

## How to resume in a local session with superpowers

After installing `superpowers` (per its README) and cloning the repo locally:

```
git checkout claude/gov-spending-investment-tool-4a4ct
git pull
claude
```

Then paste this prompt into the new session:

> Read `govspend-signals/HANDOFF.md`. We're continuing a build that started in a
> web Claude Code session. The SEC EDGAR signal box is scaffolded but untested
> and the broader command center is unbuilt. Use the superpowers brainstorming
> + planning skills to:
>
> 1. Verify the EDGAR scaffold (write tests, run them, do a live smoke poll
>    once `EDGAR_USER_AGENT` is set), and fix anything broken.
> 2. Design and plan an overnight build of the rest of the command center —
>    additional ingestors (USAspending, Federal Register, congressional trades,
>    small-cap grant scraper, Norway fund / 13F, hyperscaler capex, catalyst
>    calendar), a shared core, an aggregation / morning-digest command, and
>    inspection materials for the morning.
>
> Use git worktrees and TDD per the superpowers methodology. Commit
> incrementally to `claude/gov-spending-investment-tool-4a4ct` (or a
> superpowers-managed branch off of it) so I can inspect granular history.
> Defer anything that needs paid data feeds, audio/transcription, or a web UI;
> note those as out-of-scope rather than half-building them.

That's it. Superpowers takes over from there.
