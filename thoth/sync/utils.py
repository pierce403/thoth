from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from playwright.sync_api import Page


def parse_timestamp(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    # Slack-style numeric epoch with fractional seconds
    try:
        if raw.replace(".", "").isdigit():
            seconds = float(raw)
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    except ValueError:
        pass
    # ISO 8601
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def extract_messages(page: Page, selectors: Dict[str, str]) -> List[Dict[str, Any]]:
    return page.evaluate(
        """
        (sel) => {
          if (!sel.message_item) {
            return [];
          }
          const nodes = Array.from(document.querySelectorAll(sel.message_item));
          return nodes.map(node => {
            const getAttr = (el, attr) => el ? el.getAttribute(attr) : null;
            const query = (q) => q ? node.querySelector(q) : null;
            const text = (el) => el ? el.innerText.trim() : null;

            const authorEl = query(sel.author);
            const contentEl = query(sel.content);
            const timeEl = query(sel.timestamp);
            const replyEl = query(sel.reply_context);
            const editedEl = query(sel.edited);

            const messageId = sel.message_id_attr ? node.getAttribute(sel.message_id_attr) : null;
            const rawTimestamp = sel.timestamp_attr ? getAttr(timeEl, sel.timestamp_attr) : (timeEl ? timeEl.getAttribute("datetime") || timeEl.getAttribute("data-ts") || timeEl.innerText : null);

            const reactions = [];
            if (sel.reaction_item) {
              const reactionNodes = Array.from(node.querySelectorAll(sel.reaction_item));
              for (const reaction of reactionNodes) {
                const emojiEl = sel.reaction_emoji ? reaction.querySelector(sel.reaction_emoji) : null;
                const countEl = sel.reaction_count ? reaction.querySelector(sel.reaction_count) : null;
                const emoji = emojiEl ? (emojiEl.getAttribute("alt") || emojiEl.innerText || emojiEl.getAttribute("aria-label")) : null;
                const countText = countEl ? countEl.innerText.trim() : "1";
                reactions.push({
                  emoji: emoji || "?",
                  count: parseInt(countText || "1", 10) || 1,
                });
              }
            }

            return {
              external_id: messageId || null,
              author: text(authorEl),
              content: text(contentEl),
              content_raw: contentEl ? contentEl.innerHTML : null,
              raw_timestamp: rawTimestamp,
              edited: !!editedEl,
              reply_context: replyEl ? replyEl.innerText.trim() : null,
              reactions,
            };
          }).filter(msg => msg.external_id || msg.content);
        }
        """,
        selectors,
    )


def scroll_to_bottom(page: Page, container_selector: Optional[str]) -> None:
    if container_selector:
        page.evaluate(
            """
            (selector) => {
              const container = document.querySelector(selector);
              if (container) {
                container.scrollTop = container.scrollHeight;
              }
            }
            """,
            container_selector,
        )
        return
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")


def scroll_up(page: Page, container_selector: Optional[str], pixels: int) -> None:
    if container_selector:
        page.evaluate(
            """
            ({selector, pixels}) => {
              const container = document.querySelector(selector);
              if (container) {
                container.scrollTop = Math.max(0, container.scrollTop - pixels);
              }
            }
            """,
            {"selector": container_selector, "pixels": pixels},
        )
        return
    page.evaluate("(pixels) => window.scrollBy(0, -pixels)", pixels)
