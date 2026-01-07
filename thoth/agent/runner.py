from __future__ import annotations

import argparse
import logging
import getpass
from typing import Optional

from thoth import config as config_module
from thoth import db
from thoth import query

LOGGER = logging.getLogger(__name__)

HELP_TEXT = """
Thoth commands:
- help: show this message
- stats: show per-channel message counts
- recent: show the most recent messages
- search <term>: search recent messages containing <term>
- exit: quit (stdio mode only)
""".strip()


def format_messages(rows) -> str:
    if not rows:
        return "(no results)"
    lines = []
    for row in rows:
        content = (row.get("content") or "").strip().replace("\n", " ")
        lines.append(f"[{row.get('source')}#{row.get('channel')}] {row.get('created_at')}: {content}")
    return "\n".join(lines)


def handle_query(conn, text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if text.lower() == "help":
        return HELP_TEXT
    if text.lower() == "stats":
        rows = query.channel_counts(conn)
        if not rows:
            return "(no data)"
        return "\n".join(
            f"{row['source']}#{row['channel']}: {row['message_count']}" for row in rows
        )
    if text.lower() == "recent":
        return format_messages(query.recent_activity(conn))
    if text.lower().startswith("search "):
        term = text[7:].strip()
        return format_messages(query.search_messages(conn, term))
    return "Unknown command. Type 'help'."


def run_stdio(config_path: Optional[str]) -> None:
    config = config_module.load_config(config_path)
    conn = db.connect(config.db_path)
    db.ensure_schema(conn)

    print("Thoth is listening. Type 'help' for commands.\n")
    while True:
        try:
            text = input("thoth> ")
        except EOFError:
            break
        if text.strip().lower() == "exit":
            break
        response = handle_query(conn, text)
        if response:
            print(response)


def run_xmtp(config_path: Optional[str]) -> None:
    config = config_module.load_config(config_path)
    conn = db.connect(config.db_path)
    db.ensure_schema(conn)

    wallet_key = getpass.getpass("Enter XMTP wallet key (input hidden): ").strip()
    if not wallet_key:
        raise RuntimeError("No XMTP wallet key provided")

    try:
        from xmtp.client import Client  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "XMTP client library not available. Install an XMTP client or run with --stdio."
        ) from exc

    client = Client.from_key(wallet_key)
    LOGGER.info("XMTP client ready as %s", client.address)

    for convo in client.conversations.stream():
        for message in convo.stream_messages():
            if message.sender_address == client.address:
                continue
            response = handle_query(conn, message.content)
            if response:
                convo.send(response)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Thoth agent (XMTP)")
    parser.add_argument("--config", dest="config", default=None)
    parser.add_argument("--stdio", action="store_true", help="Use stdin/stdout instead of XMTP")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
    args = build_arg_parser().parse_args()
    if args.stdio:
        run_stdio(args.config)
        return
    run_xmtp(args.config)


if __name__ == "__main__":
    main()
