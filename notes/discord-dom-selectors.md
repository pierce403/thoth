# Discord DOM Selectors Guide

This document captures findings from investigating Discord's web UI DOM structure for the Thoth scraping project. Discord's DOM changes occasionally, so these notes serve as a reference for debugging and updating selectors.

## Last Updated
2026-01-08

## Server/Guild Navigation

### Server Sidebar
The left-hand server list (guild icons) is contained in a `<nav>` element.

**Current aria-label:** `"Servers sidebar"` (changed from `"Servers"`)

```css
/* Use partial match to be resilient to label changes */
nav[aria-label*='Servers']

/* Exact match (may break if Discord changes the label) */
nav[aria-label='Servers sidebar']
```

### Guild List Items
Each server in the sidebar has a `data-list-item-id` attribute:

```css
[data-list-item-id^='guildsnav___']
```

**Format:** `guildsnav___<guild_id>` where `<guild_id>` is either:
- A numeric ID like `1357228500523942000`
- Special value `home` for the DM/home section

**Example extraction (JavaScript):**
```javascript
const guildItems = document.querySelectorAll("[data-list-item-id^='guildsnav___']");
const guildIds = Array.from(guildItems)
  .map(el => el.getAttribute('data-list-item-id').replace('guildsnav___', ''))
  .filter(id => /^\d+$/.test(id)); // Only numeric IDs
```

### Channel Links
Channel links within the sidebar follow this pattern:
```css
a[href*='/channels/']
```

**URL format:** `/channels/<guild_id>/<channel_id>`

---

## Message Extraction

### Message Container
Messages are contained in `<li>` elements with IDs that start with `chat-messages-`:

```css
[id^='chat-messages-'], li[id^='chat-messages-']
```

**ID format:** `chat-messages-<channel_id>-<message_id>`

Alternative selectors that also work:
```css
[role='article']                    /* 50 matches in viewport */
li[class*='messageListItem']        /* 50 matches in viewport */
```

### Author/Username Extraction

**⚠️ Critical Finding:** The author selector depends on Discord's display mode (Compact vs Cozy).

#### Compact Mode Issue
In Compact Mode, using `h3 span` returns the **timestamp** first, not the username:
```
h3 span → "Wednesday, January 7, 2026 at 4:40 PM" ❌ WRONG
```

#### Working Selectors (both modes)
```css
/* Best - clean username only */
span[class*='username']

/* Also works */
h3 span[class*='username']

/* Works but includes extra metadata (server tags, separators) */
[id^='message-username-']
```

**Recommended config:**
```toml
author = "span[class*='username'], h3 span[class*='username']"
```

### Message Content
```css
div[class*='markup']
div[class*='messageContent']
[id^='message-content-']
```

### Timestamp
```css
time
```
The `datetime` attribute contains ISO 8601 format: `2025-06-18T20:56:09.999Z`

### Edited Indicator
```css
span[class*='edited']
```

### Reply Context
```css
div[class*='repliedMessage']
```

### Reactions
```css
/* Reaction container */
div[role='button'][class*='reaction']

/* Emoji within reaction */
img, span  /* Check alt attribute for emoji name */

/* Reaction count */
span  /* innerText contains the count */
```

---

## Display Modes

Discord has multiple display modes that affect DOM structure:

### Cozy Mode
- Messages are visually grouped by author
- Only the first message in a group has full author/avatar
- Subsequent messages have `groupStart` class

### Compact Mode
- Every message line includes author info
- Timestamp appears before username in `<h3>`
- Structure: `<h3><span class="timestamp">...</span><span class="username">...</span></h3>`

**Implication:** Always use class-based selectors (`[class*='username']`) rather than positional selectors (`h3 span`) to handle both modes.

---

## Scroll Container

For scrolling to load more messages:
```css
main
```

Alternative selectors:
```css
[class*='scroller'][role='group']
[class*='scrollerBase']
```

---

## Forum Channels

**⚠️ Current Limitation:** Forum channels have a different structure and the standard message selectors don't work. Forums display thread lists, not messages directly.

Forum channel URLs still follow the pattern:
```
/channels/<guild_id>/<forum_channel_id>
```

But the content structure is different - would need separate selectors for forum thread extraction.

---

## Known Issues & Gotchas

1. **Virtualized lists:** Discord uses virtual scrolling, so only ~50 messages are in the DOM at any time. Must scroll to load more.

2. **aria-label changes:** Discord occasionally changes aria-labels. Always use partial matches (`*=`) when possible.

3. **Class name obfuscation:** Discord uses CSS-in-JS with generated class names like `_5e434347c823b592-guilds`. Don't rely on exact class names - use partial matches.

4. **Rate limiting:** Opening too many channels quickly may trigger rate limits or show "Ready selector not found" warnings.

5. **Login state:** The DOM is completely different when logged out. Always verify login state before scraping.

---

## Debugging Tips

### Quick DOM Inspection (Browser Console)
```javascript
// Count messages in viewport
document.querySelectorAll("[id^='chat-messages-']").length

// Check server sidebar
document.querySelector("nav[aria-label*='Servers']")

// Test author extraction
const msg = document.querySelector("[id^='chat-messages-']");
console.log({
  username: msg.querySelector("span[class*='username']")?.innerText,
  content: msg.querySelector("div[class*='markup']")?.innerText,
  time: msg.querySelector("time")?.getAttribute("datetime")
});
```

### Verify Selector Changes
Before deploying selector changes, test in the browser console to verify they return expected results across multiple servers and display modes.
