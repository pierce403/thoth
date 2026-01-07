# Thoth Architecture

## Status
Draft, living document. Update as the system evolves.

## Goals
- Headful Playwright scraping of public community chats (Discord, Slack, Telegram).
- Slow, human-like ingestion that prioritizes recent messages, then backfills.
- Capture edits, reactions, and threading in a universal schema.
- Store data in a Postgres-friendly SQLite schema for later migration.
- Keep secrets out of code and config; prompt users to log in interactively.

## Non-goals
- No API-based ingestion (scrape only).
- No aggressive or high-rate crawling.
- No auto-authentication or secret storage.

## System overview
```
           ┌──────────────────────────┐
           │      sync.sh (loop)      │
           └────────────┬─────────────┘
                        │
                        ▼
           ┌──────────────────────────┐
           │   thoth.sync (Python)    │
           │  Playwright headful UI   │
           └────────────┬─────────────┘
                        │
                        ▼
           ┌──────────────────────────┐
           │     SQLite (thoth.db)    │
           └────────────┬─────────────┘
                        │
                        ▼
           ┌──────────────────────────┐
           │ thoth.agent (XMTP)       │
           │   query + summaries      │
           └──────────────────────────┘
```

## Components
### sync.sh
- Runs the sync runner in a continuous loop with a delay.
- Intended to be long-lived on a machine with a GUI.

### thoth.sync
- Uses Playwright in **headful** mode (forced).
- Opens a single Chromium profile with one tab per enabled source.
- Prompts for login when necessary; user completes auth in the visible browser.
- Collects messages via DOM selectors defined in config.

### Data store (SQLite)
- File: `data/thoth.db`
- Designed to be Postgres-compatible for later migration.

### thoth.agent
- Communicates as "Thoth" over XMTP (or stdio fallback).
- Currently supports basic queries (recent, search, stats).

## Data flow
1) `sync.sh` launches `python -m thoth.sync` repeatedly.
2) Each pass:
   - Opens tabs to Discord/Slack/Telegram (enabled sources).
   - Ensures login (interactive if needed).
   - Scrapes recent messages first and records them.
   - After idle cycles, scrolls upward to backfill history.
3) Data is inserted/updated in SQLite tables.
4) `thoth.agent` reads the database and answers user queries.

## Sync strategy
- Recent-first ingestion uses `recent_message_limit` to avoid heavy scans.
- If no new messages for `idle_cycles_before_backfill` cycles, switch to backfill mode.
- Backfill mode scrolls up in small steps with delays.
- Edits are captured via `message_versions` and `message.edited` events.
- Reactions are stored in `reactions` with counts.

## Data model (summary)
- `sources`: Each chat platform.
- `channels`: Channel/room metadata.
- `users`: Author identities.
- `messages`: Main message records (thread/reply fields included).
- `message_versions`: Snapshots of edited messages.
- `reactions`: Emoji reactions with counts.
- `events`: Timeline of notable events.
- `embeddings`: Placeholder for future vector storage.
- `sync_state`: Per-channel sync cursors and mode.

## Configuration
- Default config: `config/thoth.toml`
- The `sources` section defines each platform, selectors, and channel URLs.
- Selectors are expected to change; tune them as needed.

## Security & privacy
- No secrets are stored in code or config.
- Auth is done interactively in a visible browser.
- Respect community rules and platform terms.

## Operations
- Run `sync.sh` continuously on a GUI-enabled machine.
- Run `agent.sh` separately (XMTP or stdio).
- Browser profile is persisted under `data/profiles/default`.

## Observability
- Logging is standard Python logging to stdout.
- `events` table captures edit events and can be extended for more.

## Testing
- No automated tests yet.
- Validate by running a short sync pass and checking the DB.

## Roadmap
- Harden selectors and thread extraction for each platform.
- Add structured logging and metrics.
- Add export/migration to Postgres + pgvector.
- Improve XMTP agent query grammar and responses.

## Glossary
- **Headful**: Browser UI visible.
- **Backfill**: Scrolling up to capture older messages.
- **Universal schema**: Tables that map features across platforms.
