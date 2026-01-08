from __future__ import annotations

import argparse
import logging
import hashlib
import pathlib
import re
import sys
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, Page
import sqlite3

from thoth import config as config_module
from thoth import db
from thoth.sync.models import MessageData, ReactionData
from thoth.sync import tasks as task_module
from thoth.sync.utils import extract_messages, parse_timestamp, scroll_to_bottom, scroll_up

LOGGER = logging.getLogger(__name__)

LOGIN_SELECTORS = {
    "discord": "input[name='email']",
    "slack": "input[name='email']",
    "telegram": "input[type='tel'], input[name='phone_number']",
}

DISCORD_BASE = "https://discord.com"


def _normalize_discord_url(href: str) -> str:
    return urljoin(DISCORD_BASE, href)


def _infer_guild_id_from_url(url: str) -> Optional[str]:
    ids = _extract_discord_ids(url)
    if not ids:
        return None
    if ids[0] == "@me":
        return None
    return ids[0] if ids[0] else None


def _is_discord_dm_url(url: str) -> bool:
    return "/channels/@me" in (url or "")


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    base = url.split("?", 1)[0].rstrip("/")
    return base


def _clean_label(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _extract_discord_ids(href: str) -> Optional[tuple[str, str]]:
    match = re.search(r"/channels/([^/]+)/([^/]+)", href)
    if match:
        return match.group(1), match.group(2)
    match = re.search(r"/channels/([^/]+)$", href)
    if match:
        return match.group(1), ""
    return None


def discover_discord_channels(page: Page, base_url: str) -> list[dict]:
    if "discord.com/channels" not in page.url:
        page.goto(base_url, wait_until="domcontentloaded")
    try:
        page.wait_for_selector("nav[aria-label='Servers']", timeout=15000)
    except Exception:  # noqa: BLE001
        LOGGER.warning("Discord discovery: server list not found on %s", page.url)
    page.wait_for_timeout(1500)

    server_links = page.evaluate(
        """
        () => {
          const nav = document.querySelector("nav[aria-label='Servers']");
          if (!nav) return [];
          const anchors = Array.from(nav.querySelectorAll("a"));
          return anchors
            .map(el => el.getAttribute('href') || '')
            .filter(href => href.includes('/channels/'));
        }
        """
    )
    guild_ids: set[str] = set()
    for href in server_links:
        ids = _extract_discord_ids(href)
        if ids:
            guild_ids.add(ids[0])
    LOGGER.info("Discord discovery: %d server IDs from sidebar", len(guild_ids))

    channels: list[dict] = []
    seen_urls: set[str] = set()

    def collect_channels_for_guild(guild_id: str) -> None:
        channel_links = page.evaluate(
            """
            (guildId) => Array.from(document.querySelectorAll(`a[href*='/channels/${guildId}/']`))
              .map(el => ({
                href: el.getAttribute('href') || '',
                text: (el.innerText || '').trim(),
                aria: el.getAttribute('aria-label') || ''
              }))
            """,
            guild_id,
        )
        LOGGER.info(
            "Discord discovery: %d channel links found for guild %s",
            len(channel_links),
            guild_id,
        )
        for link in channel_links:
            href = link.get("href") or ""
            ids = _extract_discord_ids(href)
            if not ids:
                continue
            url = _normalize_discord_url(href)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            name = _clean_label(link.get("text") or link.get("aria") or f"channel-{ids[1]}")
            channels.append(
                {"name": name, "url": url, "guild_id": ids[0], "channel_id": ids[1]}
            )

    # Collect DMs from @me if visible
    try:
        home_link = page.locator("a[href='/channels/@me']")
        if home_link.count() > 0:
            home_link.first.click()
            page.wait_for_timeout(1200)
            collect_channels_for_guild("@me")
    except Exception:  # noqa: BLE001
        pass

    for guild_id in sorted(guild_ids):
        if guild_id == "@me":
            continue
        try:
            selector = f"nav[aria-label='Servers'] a[href*='/channels/{guild_id}']"
            locator = page.locator(selector)
            if locator.count() > 0:
                locator.first.click()
                page.wait_for_timeout(1200)
            else:
                page.goto(f"{DISCORD_BASE}/channels/{guild_id}", wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
            try:
                page.wait_for_selector(f"a[href*='/channels/{guild_id}/']", timeout=10000)
            except Exception:  # noqa: BLE001
                LOGGER.warning("Discord discovery: no channel links found for %s", guild_id)
            collect_channels_for_guild(guild_id)
        except Exception:  # noqa: BLE001
            LOGGER.warning("Discord discovery: failed to open guild %s", guild_id)
            continue

    # Fallback: use current URL's guild if we have no sidebar IDs (sometimes nav is virtualized)
    if not guild_ids:
        current_guild = _infer_guild_id_from_url(page.url)
        if current_guild:
            LOGGER.info("Discord discovery: fallback using current guild %s", current_guild)
            collect_channels_for_guild(current_guild)
    if not channels:
        raw_links = page.evaluate(
            """
            () => Array.from(document.querySelectorAll("a[href*='/channels/']"))
              .map(el => ({
                href: el.getAttribute('href') || '',
                text: (el.innerText || '').trim(),
                aria: el.getAttribute('aria-label') || ''
              }))
            """
        )
        LOGGER.info("Discord discovery fallback: %d channel links visible", len(raw_links))
        for link in raw_links:
            href = link.get("href") or ""
            ids = _extract_discord_ids(href)
            if not ids:
                continue
            url = _normalize_discord_url(href)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            name = _clean_label(link.get("text") or link.get("aria") or f"channel-{ids[1]}")
            channels.append(
                {"name": name, "url": url, "guild_id": ids[0], "channel_id": ids[1]}
            )

    return channels


class GenericScraper:
    def __init__(self, source_type: str, selectors: Dict[str, str]):
        self.source_type = source_type
        self.selectors = selectors

    def login_screen_visible(self, page: Page) -> bool:
        login_selector = LOGIN_SELECTORS.get(self.source_type)
        if not login_selector:
            return False
        return bool(page.query_selector(login_selector))

    def login_required(self, page: Page, base_url: str) -> bool:
        login_selector = LOGIN_SELECTORS.get(self.source_type)
        if not login_selector:
            return False
        page.goto(base_url, wait_until="load")
        page.wait_for_timeout(1000)
        return bool(page.query_selector(login_selector))

    def wait_for_login(self, page: Page, timeout_seconds: int = 60) -> bool:
        login_selector = LOGIN_SELECTORS.get(self.source_type)
        if not login_selector:
            return True
        if not sys.stdin.isatty():
            LOGGER.warning(
                "Login required for %s. Waiting for user login in the browser.",
                self.source_type,
            )
            last_log = time.monotonic()
            deadline = time.monotonic() + timeout_seconds
            while page.query_selector(login_selector) and time.monotonic() < deadline:
                page.wait_for_timeout(2000)
                if time.monotonic() - last_log > 30:
                    LOGGER.warning(
                        "Still waiting on %s login. Please authenticate in the browser.",
                        self.source_type,
                    )
                    last_log = time.monotonic()
        else:
            deadline = time.monotonic() + timeout_seconds
            while page.query_selector(login_selector) and time.monotonic() < deadline:
                LOGGER.warning(
                    "Login required for %s. Please authenticate in the browser.",
                    self.source_type,
                )
                input("Press Enter after completing login to re-check...")
                page.wait_for_timeout(1000)
        if page.query_selector(login_selector):
            LOGGER.warning("Login still pending for %s. Skipping for now.", self.source_type)
            return False
        ready_selector = self.selectors.get("message_item")
        if ready_selector:
            try:
                page.wait_for_selector(ready_selector, timeout=30000)
            except Exception:  # noqa: BLE001
                LOGGER.info("Continuing without ready selector for %s.", self.source_type)
        return True

    def open_channel(self, page: Page, url: str) -> None:
        if self.source_type == "discord":
            ids = _extract_discord_ids(url)
            if ids:
                selector = f"a[href*='/channels/{ids[0]}/{ids[1]}']"
                locator = page.locator(selector)
                if locator.count() > 0:
                    locator.first.click()
                    page.wait_for_timeout(1000)
                    login_selector = LOGIN_SELECTORS.get(self.source_type)
                    if login_selector and page.query_selector(login_selector):
                        self.wait_for_login(page)
                    return
        if _normalize_url(page.url) != _normalize_url(url):
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
        login_selector = LOGIN_SELECTORS.get(self.source_type)
        if login_selector and page.query_selector(login_selector):
            self.wait_for_login(page)

    def collect_messages(self, page: Page) -> Dict[str, Any]:
        raw_messages = extract_messages(page, self.selectors)
        parsed = []
        for raw in raw_messages:
            timestamp = parse_timestamp(raw.get("raw_timestamp"))
            external_id = raw.get("external_id")
            if not external_id:
                fallback = f"{raw.get('raw_timestamp')}|{raw.get('author')}|{raw.get('content')}"
                external_id = f"fallback:{hashlib.sha1(fallback.encode('utf-8')).hexdigest()}"
            msg = MessageData(
                external_id=str(external_id),
                author=raw.get("author"),
                author_external_id=raw.get("author"),
                content=raw.get("content"),
                content_raw=raw.get("content_raw"),
                created_at=timestamp,
                edited_at=timestamp if raw.get("edited") else None,
                thread_root_external_id=None,
                reply_to_external_id=None,
                reactions=[
                    ReactionData(
                        emoji=reaction.get("emoji", "?"),
                        count=reaction.get("count", 1),
                    )
                    for reaction in raw.get("reactions", [])
                ],
                metadata={
                    "raw": raw,
                    "reply_context": raw.get("reply_context"),
                },
            )
            if msg.external_id:
                parsed.append(msg)
        return {"messages": parsed}


def ingest_messages(
    conn: sqlite3.Connection,
    source_id: int,
    channel_id: int,
    messages: list[MessageData],
) -> Dict[str, int]:
    inserted = 0
    edited = 0
    for msg in messages:
        author_id = None
        if msg.author_external_id:
            author_id = db.upsert_user(
                conn,
                source_id=source_id,
                external_id=msg.author_external_id,
                handle=None,
                display_name=msg.author,
            )
        message_id, created, was_edited = db.upsert_message(
            conn,
            source_id=source_id,
            channel_id=channel_id,
            external_id=msg.external_id,
            author_id=author_id,
            content=msg.content,
            content_raw=msg.content_raw,
            created_at=msg.created_at,
            edited_at=msg.edited_at,
            thread_root_external_id=msg.thread_root_external_id,
            reply_to_external_id=msg.reply_to_external_id,
            metadata=msg.metadata,
        )
        if created:
            inserted += 1
        if was_edited:
            edited += 1
            db.record_event(
                conn,
                source_id=source_id,
                channel_id=channel_id,
                message_id=message_id,
                event_type="message.edited",
                payload={"external_id": msg.external_id},
            )
        for reaction in msg.reactions:
            if reaction.emoji:
                db.upsert_reaction(
                    conn,
                    message_id=message_id,
                    emoji=reaction.emoji,
                    count=reaction.count,
                    metadata=reaction.metadata,
                )
    return {"inserted": inserted, "edited": edited}


def sync_channel(
    page: Page,
    scraper: GenericScraper,
    conn: sqlite3.Connection,
    source_id: int,
    channel_id: int,
    channel_url: str,
    scrape_config: Dict[str, Any],
    label: str,
) -> dict:
    state = db.get_sync_state(conn, source_id, channel_id)
    mode = state["mode"] or "recent"
    idle_cycles = int(state["idle_cycles"] or 0)
    last_seen_at = state["last_seen_at"]
    oldest_seen_at = state["oldest_seen_at"]

    scraper.open_channel(page, channel_url)
    ready_selector = scraper.selectors.get("message_item")
    if ready_selector:
        try:
            page.wait_for_selector(ready_selector, timeout=30000)
        except Exception:  # noqa: BLE001
            LOGGER.info("Ready selector not found for %s; continuing.", channel_url)
    scroll_container = scraper.selectors.get("scroll_container")
    scroll_to_bottom(page, scroll_container)
    page.wait_for_timeout(int(scrape_config.get("scroll_delay_ms", 1000)))

    recent_data = scraper.collect_messages(page)
    recent_limit = int(scrape_config.get("recent_message_limit", 200))
    recent_messages = recent_data["messages"][-recent_limit:]
    if not recent_messages:
        LOGGER.warning(
            "No messages extracted for %s. Check login status and selectors.",
            label,
        )
    recent_results = ingest_messages(conn, source_id, channel_id, recent_messages)
    if recent_results["inserted"] == 0:
        idle_cycles += 1
    else:
        idle_cycles = 0

    timestamps = [msg.created_at for msg in recent_messages if msg.created_at]
    if timestamps:
        last_seen_at = max(timestamps)

    idle_threshold = int(scrape_config.get("idle_cycles_before_backfill", 6))
    if mode == "recent" and idle_cycles >= idle_threshold:
        mode = "backfill"
        idle_cycles = 0

    if mode == "backfill":
        steps = int(scrape_config.get("backfill_scroll_steps", 4))
        pixels = int(scrape_config.get("scroll_pixels", 1200))
        delay = int(scrape_config.get("scroll_delay_ms", 1500))
        backfill_timestamps = []
        backfill_inserted = 0
        backfill_edited = 0
        for _ in range(steps):
            scroll_up(page, scroll_container, pixels)
            page.wait_for_timeout(delay)
            data = scraper.collect_messages(page)
            results = ingest_messages(conn, source_id, channel_id, data["messages"])
            backfill_inserted += results["inserted"]
            backfill_edited += results["edited"]
            backfill_timestamps.extend([msg.created_at for msg in data["messages"] if msg.created_at])
        if backfill_timestamps:
            oldest_seen_at = min(backfill_timestamps)
    else:
        backfill_inserted = 0
        backfill_edited = 0

    db.update_sync_state(
        conn,
        source_id=source_id,
        channel_id=channel_id,
        mode=mode,
        last_seen_at=last_seen_at,
        oldest_seen_at=oldest_seen_at,
        cursor={"mode": mode, "idle_cycles": idle_cycles},
        idle_cycles=idle_cycles,
    )
    LOGGER.info(
        "Sync success %s mode=%s inserted=%d edited=%d backfill_inserted=%d backfill_edited=%d",
        label,
        mode,
        recent_results["inserted"],
        recent_results["edited"],
        backfill_inserted,
        backfill_edited,
    )
    return {
        "status": "ok",
        "details": (
            f"mode={mode} recent_inserted={recent_results['inserted']} "
            f"recent_edited={recent_results['edited']} "
            f"backfill_inserted={backfill_inserted} backfill_edited={backfill_edited}"
        ),
    }


def prepare_session(
    config: config_module.ThothConfig,
    playwright,
) -> tuple[sqlite3.Connection, object, list, Dict[str, Page], Dict[str, GenericScraper]]:
    conn = db.connect(config.db_path)
    db.ensure_schema(conn)

    if config.headless:
        LOGGER.warning("Headless mode requested; forcing headful browser for visibility.")
    profile_dir = pathlib.Path(config.profile_dir) / "default"
    profile_dir.mkdir(parents=True, exist_ok=True)
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=False,
        slow_mo=config.slow_mo_ms,
        viewport=None,
        args=["--start-maximized"],
    )

    enabled_sources = [source for source in config.sources if source.enabled]
    if not enabled_sources:
        LOGGER.warning("No enabled sources found. Enable at least one source in config.")
    pages_by_source: Dict[str, Page] = {}
    scrapers_by_source: Dict[str, GenericScraper] = {}

    existing_pages = list(context.pages)
    login_needed = []
    for index, source in enumerate(enabled_sources):
        page = existing_pages[index] if index < len(existing_pages) else context.new_page()
        pages_by_source[source.name] = page
        scraper = GenericScraper(source.type, source.selectors)
        scrapers_by_source[source.name] = scraper
        page.bring_to_front()
        if scraper.login_required(page, source.base_url):
            login_needed.append(source.name)

    if login_needed:
        LOGGER.warning(
            "Login required for: %s. Please authenticate in the browser tabs.",
            ", ".join(login_needed),
        )

    return conn, context, enabled_sources, pages_by_source, scrapers_by_source


def _handle_prepare_error(exc: Exception) -> None:
    message = str(exc)
    if "missing dependencies" in message.lower() or "Host system is missing dependencies" in message:
        LOGGER.error(
            "Playwright system dependencies are missing. Run: sudo playwright install-deps "
            "or install required OS packages (e.g. libxml2), then retry."
        )
        raise SystemExit(2) from exc
    raise


def run_cycle(
    conn: sqlite3.Connection,
    config: config_module.ThothConfig,
    enabled_sources,
    pages_by_source: Dict[str, Page],
    scrapers_by_source: Dict[str, GenericScraper],
) -> None:
    queue = task_module.TaskQueue()

    for source in enabled_sources:
        enabled_channels = [channel for channel in source.channels if channel.enabled]
        source_id = db.upsert_source(conn, source.name, source.type, source.base_url)
        scraper = scrapers_by_source[source.name]
        page = pages_by_source[source.name]

        if scraper.login_screen_visible(page):
            LOGGER.warning(
                "Login pending for source %s. Skipping sync tasks until login completes.",
                source.name,
            )
            queue.add(
                task_module.Task(
                    name="login_pending",
                    source=source.name,
                    channel=None,
                    reason="login screen visible; waiting for user authentication",
                    action=lambda: {"status": "pending", "details": "login screen visible"},
                )
            )
            continue

        def notification_action(page=page, scraper=scraper):
            needs_login = scraper.login_screen_visible(page)
            if needs_login:
                return {"status": "login_pending", "details": "login required"}
            page.wait_for_timeout(500)
            return {"status": "ok", "details": "checked notifications"}

        def server_check_action(page=page, scraper=scraper):
            needs_login = scraper.login_screen_visible(page)
            if needs_login:
                return {"status": "login_pending", "details": "login required"}
            page.wait_for_timeout(500)
            return {"status": "ok", "details": "checked server list"}

        queue.add(
            task_module.Task(
                name="check_notifications",
                source=source.name,
                channel=None,
                reason="periodic check for unread activity",
                action=notification_action,
            )
        )
        queue.add(
            task_module.Task(
                name="check_servers",
                source=source.name,
                channel=None,
                reason="ensure source is responsive before channel sync",
                action=server_check_action,
            )
        )

        if not enabled_channels:
            if source.type != "discord":
                LOGGER.warning(
                    "No enabled channels for source %s. Enable channels in config to sync.",
                    source.name,
                )
                continue

            existing = conn.execute(
                "SELECT id, name, url FROM channels WHERE source_id = ? ORDER BY id",
                (source_id,),
            ).fetchall()
            if existing:
                has_server_channels = any(not _is_discord_dm_url(row["url"]) for row in existing)
                if has_server_channels:
                    LOGGER.info(
                        "Using %d previously discovered Discord channels for %s.",
                        len(existing),
                        source.name,
                    )
                    for row in existing:
                        state = db.get_sync_state(conn, source_id, row["id"])
                        mode = state["mode"] or "recent"
                        reason = "read recent activity" if mode == "recent" else "backfill backlog"

                        def make_sync_action(
                            page=page,
                            scraper=scraper,
                            source_id=source_id,
                            channel_id=row["id"],
                            channel_url=row["url"],
                            label=f"{source.name}:{row['name']}",
                        ):
                            return sync_channel(
                                page,
                                scraper,
                                conn,
                                source_id,
                                channel_id,
                                channel_url,
                                config.scrape,
                                label,
                            )

                        queue.add(
                            task_module.Task(
                                name="sync_channel",
                                source=source.name,
                                channel=row["name"],
                                reason=reason,
                                action=make_sync_action,
                            )
                        )
                    continue

                LOGGER.info(
                    "Only DM channels found for %s. Triggering server discovery.",
                    source.name,
                )

            LOGGER.warning(
                "No enabled channels for source %s. Auto-discovering Discord channels.",
                source.name,
            )

            def discovery_action(
                page=page,
                scraper=scraper,
                base_url=source.base_url,
                source_name=source.name,
                source_id=source_id,
            ):
                if scraper.login_screen_visible(page):
                    return {"status": "login_pending", "details": "login required"}
                discovered = discover_discord_channels(page, base_url)
                for item in discovered:
                    channel_id = db.upsert_channel(
                        conn,
                        source_id=source_id,
                        name=item["name"],
                        external_id=item["url"],
                        url=item["url"],
                        metadata={"guild_id": item.get("guild_id"), "channel_id": item.get("channel_id")},
                    )
                    state = db.get_sync_state(conn, source_id, channel_id)
                    mode = state["mode"] or "recent"
                    reason = "read recent activity" if mode == "recent" else "backfill backlog"

                    def make_sync_action(
                        page=page,
                        scraper=scraper,
                        source_id=source_id,
                        channel_id=channel_id,
                        channel_url=item["url"],
                        label=f"{source_name}:{item['name']}",
                    ):
                        return sync_channel(
                            page,
                            scraper,
                            conn,
                            source_id,
                            channel_id,
                            channel_url,
                            config.scrape,
                            label,
                        )

                    queue.add(
                        task_module.Task(
                            name="sync_channel",
                            source=source_name,
                            channel=item["name"],
                            reason=reason,
                            action=make_sync_action,
                        )
                    )

                return {
                    "status": "ok",
                    "details": f"discovered_channels={len(discovered)}",
                }

            queue.add(
                task_module.Task(
                    name="discover_channels",
                    source=source.name,
                    channel=None,
                    reason="no channels configured; auto-discover all visible Discord channels",
                    action=discovery_action,
                )
            )
            continue

        for channel in enabled_channels:
            channel_external_id = channel.url
            channel_id = db.upsert_channel(
                conn,
                source_id=source_id,
                name=channel.name,
                external_id=channel_external_id,
                url=channel.url,
            )
            state = db.get_sync_state(conn, source_id, channel_id)
            mode = state["mode"] or "recent"
            reason = "read recent activity" if mode == "recent" else "backfill backlog"

            def make_sync_action(
                page=page,
                scraper=scraper,
                source_id=source_id,
                channel_id=channel_id,
                channel_url=channel.url,
                label=f"{source.name}:{channel.name}",
            ):
                return sync_channel(
                    page,
                    scraper,
                    conn,
                    source_id,
                    channel_id,
                    channel_url,
                    config.scrape,
                    label,
                )

            queue.add(
                task_module.Task(
                    name="sync_channel",
                    source=source.name,
                    channel=channel.name,
                    reason=reason,
                    action=make_sync_action,
                )
            )

    if not queue.tasks:
        LOGGER.warning("No tasks queued for this cycle.")
        return

    LOGGER.info("Task queue ready with %d tasks.", len(queue.tasks))
    queue.run()


def run_once(config_path: Optional[str] = None) -> None:
    config = config_module.load_config(config_path)
    with sync_playwright() as playwright:
        try:
            conn, context, enabled_sources, pages_by_source, scrapers_by_source = prepare_session(
                config, playwright
            )
        except Exception as exc:  # noqa: BLE001
            _handle_prepare_error(exc)
        run_cycle(conn, config, enabled_sources, pages_by_source, scrapers_by_source)
        context.close()


def run_forever(config_path: Optional[str] = None) -> None:
    config = config_module.load_config(config_path)
    with sync_playwright() as playwright:
        try:
            conn, context, enabled_sources, pages_by_source, scrapers_by_source = prepare_session(
                config, playwright
            )
        except Exception as exc:  # noqa: BLE001
            _handle_prepare_error(exc)
        parent_pid_env = os.getenv("THOTH_PARENT_PID")
        parent_pid = int(parent_pid_env) if parent_pid_env and parent_pid_env.isdigit() else None
        context_closed = {"closed": False}

        def _mark_closed() -> None:
            context_closed["closed"] = True

        try:
            context.on("close", lambda _: _mark_closed())
        except Exception:  # noqa: BLE001
            pass
        loop_delay = max(1, int(config.loop_delay_seconds))
        while True:
            if parent_pid and os.getppid() != parent_pid:
                LOGGER.error("Sync parent process is gone; stopping sync.")
                raise SystemExit(4)
            if context_closed["closed"]:
                LOGGER.error("Browser closed; stopping sync.")
                context.close()
                raise SystemExit(3)
            try:
                run_cycle(conn, config, enabled_sources, pages_by_source, scrapers_by_source)
            except Exception as exc:  # noqa: BLE001
                if context_closed["closed"] or "Target closed" in str(exc):
                    LOGGER.error("Browser closed; stopping sync.")
                    raise SystemExit(3) from exc
                LOGGER.exception("Sync cycle failed: %s", exc)
            LOGGER.info("Sync cycle complete. Sleeping %ds.", loop_delay)
            try:
                import time

                time.sleep(loop_delay)
            except KeyboardInterrupt:
                LOGGER.info("Sync loop interrupted; shutting down.")
                break
        context.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Thoth sync runner")
    parser.add_argument("--config", dest="config", default=None)
    parser.add_argument("--once", action="store_true", help="Run a single sync pass then exit")
    return parser


def setup_logging() -> None:
    log_dir = pathlib.Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "sync.log"
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )
    task_module.configure_task_logger(log_dir)


def main() -> None:
    setup_logging()
    args = build_arg_parser().parse_args()
    if args.once:
        run_once(args.config)
    else:
        run_forever(args.config)


if __name__ == "__main__":
    main()
