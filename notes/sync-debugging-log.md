# Sync Debugging Log

This document records debugging sessions and fixes applied to the Thoth Discord sync.

## Last Updated
2026-01-08

---

## 2026-01-07: Server Discovery Failure

### Problem
The Playwright scripts couldn't see Discord servers in the left sidebar. Discovery was finding 0-1 guild IDs instead of the expected 100+.

### Investigation
Using browser subagent, executed JavaScript to inspect the DOM:
```javascript
const serverNav = document.querySelector("nav[aria-label='Servers']");
// Returns: null ❌

const serverNav = document.querySelector("nav[aria-label*='Servers']");
// Returns: <nav> element ✅
```

### Root Cause
Discord changed the sidebar's `aria-label` from `"Servers"` to `"Servers sidebar"`. The script used an exact match selector.

### Fix
Updated 3 locations in `runner.py`:

1. **Line 62** (JavaScript selector for anchor tags):
   ```javascript
   // Before
   nav[aria-label='Servers'] a[href*='/channels/']
   // After
   nav[aria-label*='Servers'] a[href*='/channels/']
   ```

2. **Line 99** (Python wait_for_selector):
   ```python
   # Before
   page.wait_for_selector("nav[aria-label='Servers']", timeout=15000)
   # After
   page.wait_for_selector("nav[aria-label*='Servers']", timeout=15000)
   ```

3. **Line 155** (Python f-string selector):
   ```python
   # Before
   selector = f"[data-list-item-id='guildsnav___{guild_id}'], nav[aria-label='Servers'] a[href*='/channels/{guild_id}']"
   # After
   selector = f"[data-list-item-id='guildsnav___{guild_id}'], nav[aria-label*='Servers'] a[href*='/channels/{guild_id}']"
   ```

### Result
After fix: 101 server IDs detected from sidebar ✅

---

## 2026-01-07: Author Names Extracted as Timestamps

### Problem
Instead of usernames, the database stored timestamps like:
```
"Wednesday, June 26, 2024 at 12:33 PM"
```

### Investigation
Analyzed message DOM structure:
```javascript
const msg = document.querySelector("[id^='chat-messages-']");

// Testing different selectors:
msg.querySelector("h3 span")?.innerText
// Returns: "Wednesday, January 7, 2026 at 4:40 PM" ❌

msg.querySelector("span[class*='username']")?.innerText
// Returns: "[REAP] Michael JD" ✅
```

### Root Cause
In Discord's Compact Mode, the `<h3>` header contains both timestamp and username spans:
```html
<h3>
  <span class="timestamp">Wednesday, January 7, 2026 at 4:40 PM</span>
  <span class="username">JessieRedBoots</span>
</h3>
```

The `h3 span` selector matched the first span (timestamp) instead of the username.

### Fix
Updated `config/thoth.toml`:
```toml
# Before
author = "h3 span"

# After
author = "span[class*='username'], h3 span[class*='username']"
```

### Result
Usernames now correctly extracted: `shaw`, `Odilitime`, `Matthew_Khouzam`, etc. ✅

---

## 2026-01-07: Noisy Author Names with Metadata

### Problem
Some author names included extra text:
```
"[REAP] Michael JD\nREAP\n:\n "
```

### Investigation
The `[id^='message-username-']` selector includes the full clickable element which contains server tags and separators.

### Fix
Changed selector priority in config:
```toml
# Before (noisy selector first)
author = "[id^='message-username-'], span[class*='username'], h3 span[class*='username']"

# After (clean selector first)
author = "span[class*='username'], h3 span[class*='username']"
```

### Result
Clean usernames without extra metadata ✅

---

## 2026-01-07: Focus on Discord Only

### Change
Disabled Slack and Telegram sources to focus debugging efforts:

```toml
# Slack
enabled = false

# Telegram  
enabled = false
```

This eliminated login warnings and allowed sync to proceed without waiting for authentication on other platforms.

---

## Performance Observations

### Message Counts (2026-01-07 session)
- Initial: 109 messages
- After server discovery fix: 1,538 messages
- After author selector fix: 2,000+ messages
- Channels discovered: 310
- Channels with messages: 70+

### Sync Timing
- Each channel sync takes ~3-10 seconds
- Full cycle through 310 channels: ~15-30 minutes
- Forum channels are skipped (no message extraction)

### Known Limitations
1. Forum channels use different DOM structure - not supported
2. Only ~50 messages visible in viewport at a time (virtual scrolling)
3. Backfill mode slowly scrolls up to get historical messages
4. Some servers may be inaccessible (left/banned) - these log warnings

---

## Useful Log Patterns

### Successful sync
```
INFO Sync success discord:Text #general mode=recent inserted=50 edited=0
```

### Discovery stats
```
INFO Discord discovery: 101 server IDs from sidebar
INFO Discord discovery: 21 channel links found for guild 1002292111942635562
```

### Warning signs
```
WARNING No messages extracted for discord:Forum ... Check login status and selectors.
WARNING Discord discovery: no channel links found for 1070046503302877216
```

### Login issues
```
WARNING Login required for: slack. Please authenticate in the browser tabs.
WARNING Login pending for source slack. Skipping sync tasks until login completes.
```
