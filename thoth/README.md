# Thoth Python Package

This is the main Python package for Thoth. It contains modules for syncing, querying, and the XMTP agent.

## Module Structure

```
thoth/
├── __init__.py      # Package initialization
├── config.py        # Configuration loading and parsing
├── db.py            # Database operations (SQLite)
├── query.py         # Message query interface
├── agent/           # XMTP agent for message queries
└── sync/            # Browser-based message scraping
```

## Core Modules

### config.py

Loads and parses the TOML configuration file.

**Key classes:**
- `ThothConfig` - Main configuration dataclass
- `SourceConfig` - Per-source (Discord/Slack/Telegram) settings
- `ChannelConfig` - Per-channel settings

**Usage:**
```python
from thoth.config import load_config

config = load_config()  # Uses default path or THOTH_CONFIG env
config = load_config("/path/to/custom.toml")
```

### db.py

Database operations using SQLite.

**Key functions:**
- `connect(path)` - Get database connection
- `ensure_schema(conn)` - Create tables if needed
- `upsert_source/channel/user/message()` - Insert or update records
- `upsert_reaction()` - Add reactions to messages
- `get_sync_state()` / `update_sync_state()` - Track sync progress

### query.py

High-level query interface for searching messages.

**Usage:**
```python
from thoth.query import search_messages

results = search_messages(
    query="keyword",
    channel="general",
    author="username",
    limit=50
)
```

## Subpackages

### sync/

Browser-based message scraping using Playwright. See `sync/README.md`.

### agent/

XMTP-based agent for querying messages via chat. See `agent/README.md`.

## Running

```bash
# Run sync
python -m thoth.sync

# Run sync once (no loop)
python -m thoth.sync --once

# Run agent
python -m thoth.agent
```
