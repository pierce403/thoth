# Thoth

Thoth is an agentic assistant that monitors public community chats (Discord, Slack, Telegram) and stores message data in a Postgres-compatible SQLite schema. It slowly catches up on recent activity first, then backfills older history. A companion agent communicates with users over XMTP to explore the captured data.

## Goals
- **Headful Playwright scraping** (browser visible at all times)
- **Slow, human-like navigation** focused on recent messages
- **Universal capture** of edits, reactions, and threading
- **SQLite schema compatible with Postgres** for easy migration/pgvector work
- **No secrets** in code or env; login happens interactively in the visible browser

## Quickstart
1) Copy and edit the config:

```bash
cp config/thoth.toml config/thoth.local.toml
```

Update `config/thoth.local.toml` with the channels you want to monitor. Selectors are intentionally exposed so you can tune them if the DOM changes.

2) Run the sync loop (bootstraps dependencies and opens the browser):

```bash
./sync.sh --config config/thoth.local.toml
```

3) Run the agent (XMTP):

```bash
./agent.sh --config config/thoth.local.toml
```

The XMTP agent prompts for your wallet key at runtime (not stored). If the sync script reaches a login screen, authenticate in the visible browser and return to the terminal when prompted.

If you don't have XMTP configured yet, you can run the agent in local stdio mode:

```bash
./agent.sh --config config/thoth.local.toml --stdio
```

To run a single sync pass and exit:

```bash
python -m thoth.sync --config config/thoth.local.toml --once
```

## Architecture
- `sync.sh` runs a **continuous loop** that calls `python -m thoth.sync` once per pass.
- `thoth.sync` opens Playwright headful and performs one gentle sync cycle.
- `thoth.db` stores messages, reactions, edits, and thread relationships.
- `agent.sh` runs the XMTP-connected assistant as "Thoth".

## Database (SQLite, Postgres-friendly)
Tables are designed for easy migration:
- `sources`, `channels`, `users`
- `messages` (with `reply_to_external_id`, `thread_root_external_id`)
- `message_versions` (edits)
- `reactions`
- `events`
- `embeddings` (placeholder for future pgvector work)
- `sync_state`

## Config notes
- `headless = false` is required to keep the browser visible.
- `slow_mo_ms` and `scroll_delay_ms` keep scraping gentle.
- Each source defines selectors for message extraction; start with defaults, then refine.

## Limitations
- DOM selectors for Discord/Slack/Telegram change frequently; expect to tune them.
- XMTP integration requires local wallet setup and a compatible XMTP client library.

## Safety & Ethics
Use Thoth only on communities where you have access and permission to read. Respect platform terms and community rules.
