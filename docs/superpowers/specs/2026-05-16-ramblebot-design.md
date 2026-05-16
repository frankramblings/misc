# RambleBot — Design Spec
**Date:** 2026-05-16
**Status:** Approved

## Overview

RambleBot is a personal institutional memory system built from Claude Code conversation transcripts collected across Frank's tailnet. It distills how Frank builds into a portable knowledge base and serves it as an MCP server that any Claude Code session or openclaw instance can consume as passive context.

Inspired by Adam Lisagor's "Lysigor" concept: six months of building history, turned into an intelligence you can consult from any future development session.

## Goals

- Collect all Claude Code transcripts from every tailnet machine into one central archive
- Collect all openclaw conversation transcripts from bespin into the same archive
- Distill recurring patterns, preferences, and processes into a human-readable document
- Embed transcript chunks for semantic search
- Serve both as an HTTP MCP server accessible to Claude Code and openclaw

## Non-Goals

- Real-time indexing (nightly batch is sufficient)
- Any UI beyond the MCP interface
- Synology support (excluded by design)

---

## Architecture

```
bespin (Mac Mini, always-on)
├── sweep.sh          pull transcripts from all hosts → archive/
├── ingest.py         parse + chunk JSONL → structured records
├── embed.py          Voyage AI embeddings → ChromaDB
├── distill.py        OpenAI Codex → dated snapshot doc
├── pipeline.sh       orchestrates sweep → ingest → embed (nightly)
└── mcp_server.py     HTTP MCP server (persistent launchd service)

Source hosts (SSH targets from bespin):
  wis-a422  MacBook Pro   (swept when online, skipped when asleep)
  endor     Ubuntu server (always reachable)
  bespin    Mac Mini      (local, always-on)
```

All data lives on bespin. Nothing depends on wis-a422 being online.

---

## Components

### 1. sweep.sh (moved from wis-a422 to bespin)

Unchanged logic from the existing script. `bespin` becomes the `local:` host. `wis-a422` and `endor` become SSH targets. Requires passwordless SSH from bespin to both.

Unreachable hosts are skipped gracefully — already handled by the existing script.

In addition to `~/.claude/` directories, the local bespin sweep also includes `~/.openclaw/agents/` so openclaw session transcripts land in the same archive under `archive/bespin/.openclaw/...`.

Archive destination: `~/ramblebot/archive/`

### 2. ingest.py

Walks `archive/`, detects the transcript format, and dispatches to the appropriate parser. Outputs a unified chunk schema regardless of source.

**Two parsers:**

**Claude Code parser** — handles `.jsonl` files under `.claude/projects/`. Extracts user↔assistant message pairs.

**openclaw parser** — handles `<uuid>.trajectory.jsonl` files under `.openclaw/agents/*/sessions/`. Prefers trajectory files (richer data); falls back to plain `.jsonl` if no trajectory exists. Skips tombstones (filenames containing `.deleted.` or `.reset.`). Skips `.trajectory-path.json` pointer files. Extracts conversation turns from structured event data.

**Unified chunk metadata:**

| Field | Source |
|---|---|
| `source` | `claude-code` or `openclaw` |
| `host` | archive subdirectory name |
| `project` | derived from `cwd` (Claude Code) or agent path (openclaw) |
| `session_id` | `sessionId` / session UUID |
| `timestamp` | `timestamp` / `ts` field |
| `role` | `user` or `assistant` |
| `text` | message content |
| `provider` | model provider (openclaw only, e.g. `anthropic`, `openai`) |
| `model_id` | model used (openclaw only) |

**Claude Code skips:** subagent files (`/subagents/` path), system messages, tool result entries, permission-mode entries.

**Idempotent:** tracks processed files by SHA-256 hash in a local state file (`~/ramblebot/.ingest_state.json`). Re-runs only process new or changed files.

Output: structured records appended to `~/ramblebot/.ingest_staging.jsonl`, consumed by embed.py.

### 3. embed.py

Reads staged chunks from ingest.py. Sends text to Voyage AI (`voyage-3-lite`) in batches. Stores vectors + metadata in ChromaDB at `~/ramblebot/chroma/`.

**Incremental:** checks chunk IDs already present in ChromaDB, skips them. Only new chunks are embedded.

**Collection name:** `ramblebot`

### 4. distill.py

Reads a sample of transcript chunks from the archive — weighted toward recent sessions, spread across all projects, hosts, and sources. Sends batches to OpenAI Codex API with a prompt designed to extract:

- Naming conventions and project structure preferences
- Architectural decision patterns
- Recurring instructions given to Claude or openclaw (what Frank always repeats)
- Debugging and problem-solving approaches
- Thinking patterns and reasoning style (surfaced from openclaw conversations)
- Tool and workflow preferences
- Per-project context (SocialFusion, undercast, granola-archiver, etc.)

Output: `~/ramblebot/distilled/ramblebot-YYYY-MM-DD.md`

After writing, updates the symlink: `~/ramblebot/ramblebot.md` → `distilled/ramblebot-YYYY-MM-DD.md`

**Schedule:** weekly (separate launchd job from the nightly pipeline). Distillation is the only step that calls the OpenAI API — embed.py uses Voyage AI free tier.

### 5. pipeline.sh

Nightly launchd job on bespin. Runs in order:

```
sweep.sh → ingest.py → embed.py
```

Distillation is a separate weekly launchd job that just calls `distill.py`.

### 6. mcp_server.py

Python HTTP MCP server using the `mcp` SDK. Runs as a persistent `launchd` service on bespin on port `8765`.

**Exposes:**

- **Resource `ramblebot://identity`** — reads and serves `~/ramblebot/ramblebot.md` (the distilled doc). This is the passive context resource loaded into every Claude Code and openclaw session automatically.
- **Tool `ramblebot_search`** — accepts a query string, embeds it via Voyage AI, queries ChromaDB, returns the top-k most relevant transcript excerpts with metadata (host, project, timestamp).

**Clients:**
- Claude Code on any tailnet machine: configured in `~/.claude/mcp_servers.json` pointing to `http://bespin.bicolor-triceratops.ts.net:PORT`
- openclaw on bespin: connects to `http://localhost:PORT`

No API calls at runtime for resource serving. `ramblebot_search` calls Voyage AI only when invoked (not on passive load).

---

## File Layout on bespin

```
~/ramblebot/
  archive/                        # swept transcripts, organized by host/path
    bespin/
      Users/frankemanuele/.claude/   # Claude Code transcripts
      Users/frankemanuele/.openclaw/ # openclaw trajectory transcripts
    endor/
    wis-a422/
  chroma/                         # ChromaDB vector store
  distilled/                      # dated distillation snapshots
    ramblebot-2026-05-16.md
    ramblebot-2026-05-23.md
    ...
  ramblebot.md                    # symlink → latest distilled snapshot
  .ingest_state.json              # tracks processed file hashes
  pipeline/
    sweep.sh
    ingest.py
    embed.py
    distill.py
    pipeline.sh
    mcp_server.py
    requirements.txt
  logs/
    sweep.log
    pipeline.log
    mcp_server.log
```

---

## Data Flow

```
[wis-a422 transcripts] ──ssh──┐
[endor transcripts]    ──ssh──┤──▶ sweep.sh ──▶ archive/ ──▶ ingest.py ──▶ embed.py ──▶ chroma/
[bespin transcripts]   local──┘                   │
                                                  └──────────────────────▶ distill.py ──▶ distilled/
                                                                                              │
                                                                         ramblebot.md ◀── symlink

                              Claude Code (any machine) ──────────────────▶ mcp_server.py ◀── chroma/
                              openclaw (bespin)         ──────────────────▶ mcp_server.py     ramblebot.md
```

---

## External Dependencies

| Service | Purpose | Cost |
|---|---|---|
| Voyage AI (`voyage-3-lite`) | Embeddings | Free tier (200M tokens/month) |
| OpenAI Codex API | Distillation | Standard API rates, weekly call only |

---

## Setup Requirements

1. Passwordless SSH from bespin → wis-a422 and bespin → endor
2. Voyage AI API key on bespin
3. OpenAI API key on bespin
4. Python 3.11+ on bespin
5. `mcp`, `chromadb`, `voyageai`, `openai` Python packages
6. launchd plist files for: nightly pipeline, weekly distillation, persistent MCP server

---

## Success Criteria

- Every Claude Code session on any tailnet machine automatically has Frank's building patterns in context
- openclaw on bespin reads from the same MCP server
- Nightly sweep picks up new transcripts from all online hosts
- Weekly distillation keeps the identity doc current as new work accumulates
- `ramblebot_search` returns relevant past transcript excerpts when queried
