# Config Directory

This directory contains configuration files for the Thoth sync system.

## Files

### thoth.toml

The main configuration file in TOML format. Controls all aspects of the sync process.

#### Sections

**`[thoth]`** - Core settings
```toml
[thoth]
db_path = "data/thoth.db"       # SQLite database location
profile_dir = "data/profiles"   # Browser profile storage
headless = false                # Run browser headless (false recommended)
slow_mo_ms = 250                # Delay between browser actions (ms)
loop_delay_seconds = 20         # Pause between sync cycles
```

**`[scrape]`** - Scraping behavior
```toml
[scrape]
recent_message_limit = 200      # Max messages per channel per cycle
idle_cycles_before_backfill = 6 # Cycles before switching to backfill mode
backfill_scroll_steps = 4       # Scroll iterations during backfill
scroll_delay_ms = 1500          # Delay after scrolling
scroll_pixels = 1200            # Pixels to scroll per step
```

**`[[sources]]`** - Platform configurations (one per source)
```toml
[[sources]]
name = "discord"
type = "discord"
base_url = "https://discord.com/channels/@me"
enabled = true

  [sources.selectors]
  scroll_container = "main"
  message_item = "[id^='chat-messages-']"
  author = "span[class*='username']"
  content = "div[class*='markup']"
  timestamp = "time"
  # ... more selectors
```

**`[[sources.channels]]`** - Specific channels to sync (optional)
```toml
  [[sources.channels]]
  name = "my-channel"
  url = "https://discord.com/channels/SERVER_ID/CHANNEL_ID"
  enabled = true
```

#### Supported Source Types

| Type | Status | Notes |
|------|--------|-------|
| `discord` | ✅ Fully supported | Auto-discovers all servers and channels |
| `slack` | 🚧 Partial | Requires manual channel configuration |
| `telegram` | 🚧 Partial | Requires manual channel configuration |

## Creating Custom Configurations

You can specify an alternate config file:
```bash
python -m thoth.sync --config /path/to/custom.toml
```

Or via environment variable:
```bash
export THOTH_CONFIG=/path/to/custom.toml
python -m thoth.sync
```
