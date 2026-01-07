# Thoth TODO

## Core scraping
- Verify and tune CSS selectors per platform (Discord/Slack/Telegram).
- Add robust detection of login state and post-login ready state.
- Improve thread/reply extraction and map thread roots across platforms.
- Capture per-reaction user lists where supported (optional).

## Data + search
- Add optional FTS5 index and/or pgvector-compatible embeddings pipeline.
- Add export/migration helper to Postgres + pgvector.

## Agent (XMTP)
- Wire in XMTP client credentials and message loop.
- Add richer query grammar (channels, authors, date ranges).

## Reliability
- Add structured logging + per-source metrics.
- Add health checks + alerts when scraping stalls.
