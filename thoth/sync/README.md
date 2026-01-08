# Sync Module

Browser-based message scraping using Playwright. This module handles the core synchronization logic for pulling messages from Discord, Slack, and Telegram.

## Files

### runner.py

The main sync orchestrator. Contains:

- `GenericScraper` - Platform-agnostic scraping logic
- `discover_discord_channels()` - Auto-discover Discord servers and channels
- `sync_channel()` - Sync a single channel
- `run_cycle()` - Execute one sync cycle across all sources
- `run_forever()` - Continuous sync loop
- `run_once()` - Single sync pass

**Entry points:**
```python
from thoth.sync.runner import run_once, run_forever

run_once()     # Single sync pass
run_forever()  # Continuous loop
```

### tasks.py

Task queue system for organizing sync work.

**Classes:**
- `Task` - Single unit of work (sync one channel, check notifications, etc.)
- `TaskQueue` - Queue of tasks to execute with logging

**Task types:**
- `check_notifications` - Check for unread activity
- `check_servers` - Verify source is responsive
- `discover_channels` - Auto-discover channels
- `sync_channel` - Sync messages from a channel
- `login_pending` - Waiting for authentication

### models.py

Data models for scraped content.

**Classes:**
- `MessageData` - Scraped message with author, content, timestamp
- `ReactionData` - Emoji reaction with count

### utils.py

Utility functions for browser interaction.

**Functions:**
- `extract_messages(page, selectors)` - Extract messages from current page
- `parse_timestamp(raw)` - Convert various timestamp formats to ISO 8601
- `scroll_to_bottom(page, container)` - Scroll to load recent messages
- `scroll_up(page, container, pixels)` - Scroll up for backfill

## Running

```bash
# Via module
python -m thoth.sync

# With options
python -m thoth.sync --once           # Single pass
python -m thoth.sync --config alt.toml # Custom config
```

## Sync Flow

1. **Session Setup** - Launch browser, load profiles, check login state
2. **Discovery** (Discord) - Find all servers and channels
3. **Task Queue** - Build queue of channels to sync
4. **Execution** - For each channel:
   - Navigate to channel
   - Extract visible messages
   - Upsert to database
   - Track sync state
5. **Loop** - Sleep and repeat (unless `--once`)

## Sync Modes

**Recent Mode:**
- Scrolls to bottom
- Collects newest messages
- Switches to backfill after N idle cycles

**Backfill Mode:**
- Scrolls up to load history
- Collects older messages
- Tracks oldest seen timestamp
