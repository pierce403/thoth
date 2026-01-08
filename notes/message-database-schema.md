# Message Database Schema & Requirements

This document describes the data model and requirements for the Thoth message database.

## Last Updated
2026-01-08

---

## Overview

Thoth stores scraped messages in a SQLite database. The schema supports:
- Multiple sources (Discord, Slack, Telegram)
- Multiple channels per source
- Message threading and replies
- Reactions with counts
- User tracking
- Sync state management

---

## Core Tables

### sources
Represents a chat platform instance.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| name | TEXT | Human-readable name (e.g., "discord") |
| type | TEXT | Platform type: discord, slack, telegram |
| base_url | TEXT | Base URL for the platform |

### channels
Represents a specific channel/conversation.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| source_id | INTEGER FK | Reference to sources table |
| name | TEXT | Channel name (e.g., "#general") |
| external_id | TEXT | Platform-specific channel ID or URL |
| url | TEXT | Full URL to the channel |
| metadata | JSON | Additional channel info (guild_id, channel_id) |

### users
Represents message authors.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| source_id | INTEGER FK | Reference to sources table |
| external_id | TEXT | Platform-specific user ID |
| handle | TEXT | Username/handle |
| display_name | TEXT | Display name (what appears in UI) |

### messages
Core message table.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| source_id | INTEGER FK | Reference to sources table |
| channel_id | INTEGER FK | Reference to channels table |
| external_id | TEXT | Platform-specific message ID |
| author_id | INTEGER FK | Reference to users table |
| content | TEXT | Plain text message content |
| content_raw | TEXT | HTML/raw content with formatting |
| created_at | TEXT | ISO 8601 timestamp |
| edited_at | TEXT | ISO 8601 timestamp (if edited) |
| thread_root_external_id | TEXT | External ID of thread root message |
| reply_to_external_id | TEXT | External ID of replied-to message |
| metadata | JSON | Additional message data |

### reactions
Stores emoji reactions on messages.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| message_id | INTEGER FK | Reference to messages table |
| emoji | TEXT | Emoji character or name |
| count | INTEGER | Number of reactions |
| metadata | JSON | Additional reaction data |

### sync_state
Tracks synchronization progress per channel.

| Column | Type | Description |
|--------|------|-------------|
| source_id | INTEGER FK | Reference to sources table |
| channel_id | INTEGER FK | Reference to channels table |
| mode | TEXT | Current mode: "recent" or "backfill" |
| last_seen_at | TEXT | Timestamp of most recent message seen |
| oldest_seen_at | TEXT | Timestamp of oldest message seen |
| cursor | JSON | Arbitrary cursor data for pagination |
| idle_cycles | INTEGER | Count of sync cycles with no new messages |

### events
Audit log of significant events.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| source_id | INTEGER FK | Reference to sources table |
| channel_id | INTEGER FK | Reference to channels table |
| message_id | INTEGER FK | Reference to messages table (optional) |
| event_type | TEXT | Event type (e.g., "message.edited") |
| payload | JSON | Event-specific data |
| created_at | TEXT | When the event was recorded |

---

## Key Relationships

```
sources
  └── channels (1:N)
  └── users (1:N)
  └── messages (1:N)

channels
  └── messages (1:N)
  └── sync_state (1:1)

messages
  └── reactions (1:N)
  └── users (N:1 via author_id)
```

---

## Upsert Behavior

Messages are upserted based on `(source_id, external_id)`:
- If message exists: Update content, edited_at, metadata
- If message is new: Insert with all fields

This allows:
1. Re-syncing without duplicates
2. Detecting message edits
3. Idempotent sync operations

---

## Sync Modes

### Recent Mode
- Default mode for active channels
- Scrolls to bottom and collects visible messages
- Switches to backfill after N idle cycles (no new messages)

### Backfill Mode
- Scrolls up to collect historical messages
- Collects older messages each cycle
- Tracks `oldest_seen_at` to know how far back we've gone

### Idle Cycle Tracking
- `idle_cycles` counts consecutive syncs with 0 new messages
- When `idle_cycles >= idle_cycles_before_backfill`, mode switches to backfill
- Backfill resets idle_cycles

---

## Data Quality Requirements

### Message External ID
Every message must have a unique external ID. If the platform doesn't provide one, generate a fallback:
```python
fallback = f"fallback:{sha1(timestamp|author|content)}"
```

### Timestamps
- Store as ISO 8601 strings with timezone
- Discord provides: `2025-06-18T20:56:09.999Z`
- Slack provides: Unix epoch with fractional seconds

### Author Names
- Store the display name as shown in the UI
- Avoid extracting timestamps as author names (see discord-dom-selectors.md)

### Content
- `content`: Plain text, newlines preserved
- `content_raw`: Original HTML/formatting for rich rendering

---

## Indexing Recommendations

For efficient queries:
```sql
CREATE INDEX idx_messages_channel ON messages(channel_id);
CREATE INDEX idx_messages_created ON messages(created_at);
CREATE INDEX idx_messages_external ON messages(source_id, external_id);
CREATE INDEX idx_users_external ON users(source_id, external_id);
```

---

## Future Considerations

### Full-Text Search (FTS5)
Add FTS5 virtual table for message content search:
```sql
CREATE VIRTUAL TABLE messages_fts USING fts5(content, content='messages', content_rowid='id');
```

### Vector Embeddings
For semantic search, add embeddings column or separate table:
```sql
CREATE TABLE message_embeddings (
  message_id INTEGER PRIMARY KEY,
  embedding BLOB  -- or use pgvector in Postgres
);
```

### Thread Extraction
Current limitation: Thread relationships aren't fully extracted. Would need:
- Better detection of thread root messages
- Extraction of thread metadata
- Reply chain reconstruction
