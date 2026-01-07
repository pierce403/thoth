from __future__ import annotations

import argparse
import logging
import hashlib
import pathlib
import re
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


def _extract_discord_ids(href: str) -> Optional[tuple[str, str]]:
    match = re.search(r"/channels/([^/]+)/([^/]+)", href)
    if not match:
        return None
    return match.group(1), match.group(2)


def discover_discord_channels(page: Page, base_url: str) -> list[dict]:
    page.goto(base_url, wait_until="load")
    page.wait_for_timeout(1000)
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
    guild_ids: set[str] = set()
    for link in raw_links:
        ids = _extract_discord_ids(link.get("href", ""))
        if ids:
            guild_ids.add(ids[0])

    channels: list[dict] = []
    seen_urls: set[str] = set()
    for guild_id in sorted(guild_ids):
        guild_url = f"{DISCORD_BASE}/channels/{guild_id}"
        page.goto(guild_url, wait_until="load")
        page.wait_for_timeout(1200)
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
        for link in channel_links:
            href = link.get("href") or ""
            ids = _extract_discord_ids(href)
            if not ids:
                continue
            url = _normalize_discord_url(href)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            name = link.get("text") or link.get("aria") or f"channel-{ids[1]}"
            channels.append({"name": name, "url": url, "guild_id": ids[0], "channel_id": ids[1]})

    return channels


class GenericScraper:
    def __init__(self, source_type: str, selectors: Dict[str, str]):
        self.source_type = source_type
        self.selectors = selectors

    def login_required(self, page: Page, base_url: str) -> bool:
        login_selector = LOGIN_SELECTORS.get(self.source_type)
        if not login_selector:
            return False
        page.goto(base_url, wait_until="load")
        page.wait_for_timeout(1000)
        return bool(page.query_selector(login_selector))

    def wait_for_login(self, page: Page) -> None:
        login_selector = LOGIN_SELECTORS.get(self.source_type)
        if not login_selector:
            return
        while page.query_selector(login_selector):
            LOGGER.warning("Login required for %s. Please authenticate in the browser.", self.source_type)
            input("Press Enter after completing login to re-check...")
            page.wait_for_timeout(1000)
        ready_selector = self.selectors.get("message_item")
        if ready_selector:
            try:
                page.wait_for_selector(ready_selector, timeout=30000)
            except Exception:  # noqa: BLE001
                LOGGER.info("Continuing without ready selector for %s.", self.source_type)

    def open_channel(self, page: Page, url: str) -> None:
        page.goto(url, wait_until="load")
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
        input("Press Enter after completing login in all tabs...")

    for source in enabled_sources:
        if source.name in login_needed:
            page = pages_by_source[source.name]
            page.bring_to_front()
            scrapers_by_source[source.name].wait_for_login(page)

    return conn, context, enabled_sources, pages_by_source, scrapers_by_source


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

        def notification_action(page=page, scraper=scraper, base_url=source.base_url):
            needs_login = scraper.login_required(page, base_url)
            if needs_login:
                scraper.wait_for_login(page)
                return {"status": "login", "details": "login required"}
            page.wait_for_timeout(500)
            return {"status": "ok", "details": "checked notifications"}

        def server_check_action(page=page, scraper=scraper, base_url=source.base_url):
            needs_login = scraper.login_required(page, base_url)
            if needs_login:
                scraper.wait_for_login(page)
                return {"status": "login", "details": "login required"}
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
                needs_login = scraper.login_required(page, base_url)
                if needs_login:
                    scraper.wait_for_login(page)
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
        conn, context, enabled_sources, pages_by_source, scrapers_by_source = prepare_session(
            config, playwright
        )
        run_cycle(conn, config, enabled_sources, pages_by_source, scrapers_by_source)
        context.close()


def run_forever(config_path: Optional[str] = None) -> None:
    config = config_module.load_config(config_path)
    with sync_playwright() as playwright:
        conn, context, enabled_sources, pages_by_source, scrapers_by_source = prepare_session(
            config, playwright
        )
        loop_delay = max(1, int(config.loop_delay_seconds))
        while True:
            run_cycle(conn, config, enabled_sources, pages_by_source, scrapers_by_source)
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
