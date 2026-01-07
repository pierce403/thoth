import json
import pathlib
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional, Tuple


def connect(db_path: str) -> sqlite3.Connection:
    path = pathlib.Path(db_path)
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            base_url TEXT,
            metadata_json TEXT,
            UNIQUE(name, type)
        );

        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL,
            name TEXT,
            external_id TEXT,
            url TEXT,
            is_dm INTEGER DEFAULT 0,
            metadata_json TEXT,
            UNIQUE(source_id, external_id),
            FOREIGN KEY(source_id) REFERENCES sources(id)
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL,
            external_id TEXT NOT NULL,
            handle TEXT,
            display_name TEXT,
            metadata_json TEXT,
            UNIQUE(source_id, external_id),
            FOREIGN KEY(source_id) REFERENCES sources(id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            external_id TEXT NOT NULL,
            author_id INTEGER,
            thread_root_external_id TEXT,
            reply_to_external_id TEXT,
            content TEXT,
            content_raw TEXT,
            created_at TEXT,
            edited_at TEXT,
            deleted_at TEXT,
            is_deleted INTEGER DEFAULT 0,
            metadata_json TEXT,
            UNIQUE(source_id, external_id),
            FOREIGN KEY(source_id) REFERENCES sources(id),
            FOREIGN KEY(channel_id) REFERENCES channels(id),
            FOREIGN KEY(author_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS message_versions (
            id INTEGER PRIMARY KEY,
            message_id INTEGER NOT NULL,
            captured_at TEXT NOT NULL,
            content TEXT,
            content_raw TEXT,
            metadata_json TEXT,
            FOREIGN KEY(message_id) REFERENCES messages(id)
        );

        CREATE TABLE IF NOT EXISTS reactions (
            id INTEGER PRIMARY KEY,
            message_id INTEGER NOT NULL,
            user_id INTEGER,
            emoji TEXT NOT NULL,
            count INTEGER DEFAULT 1,
            created_at TEXT,
            metadata_json TEXT,
            UNIQUE(message_id, emoji),
            FOREIGN KEY(message_id) REFERENCES messages(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL,
            channel_id INTEGER,
            message_id INTEGER,
            type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload_json TEXT,
            FOREIGN KEY(source_id) REFERENCES sources(id),
            FOREIGN KEY(channel_id) REFERENCES channels(id),
            FOREIGN KEY(message_id) REFERENCES messages(id)
        );

        CREATE TABLE IF NOT EXISTS embeddings (
            id INTEGER PRIMARY KEY,
            message_id INTEGER NOT NULL,
            model TEXT NOT NULL,
            embedding BLOB,
            created_at TEXT NOT NULL,
            metadata_json TEXT,
            UNIQUE(message_id, model),
            FOREIGN KEY(message_id) REFERENCES messages(id)
        );

        CREATE TABLE IF NOT EXISTS sync_state (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            mode TEXT NOT NULL,
            last_seen_at TEXT,
            oldest_seen_at TEXT,
            cursor_json TEXT,
            idle_cycles INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL,
            UNIQUE(source_id, channel_id),
            FOREIGN KEY(source_id) REFERENCES sources(id),
            FOREIGN KEY(channel_id) REFERENCES channels(id)
        );

        CREATE INDEX IF NOT EXISTS idx_messages_channel_created
            ON messages(channel_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_events_source_created
            ON events(source_id, created_at);
        """
    )
    conn.commit()


def _json_dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=True)


def upsert_source(conn: sqlite3.Connection, name: str, source_type: str, base_url: str) -> int:
    conn.execute(
        """
        INSERT INTO sources (name, type, base_url)
        VALUES (?, ?, ?)
        ON CONFLICT(name, type) DO UPDATE SET base_url = excluded.base_url
        """,
        (name, source_type, base_url),
    )
    row = conn.execute(
        "SELECT id FROM sources WHERE name = ? AND type = ?",
        (name, source_type),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def upsert_channel(
    conn: sqlite3.Connection,
    source_id: int,
    name: str,
    external_id: Optional[str],
    url: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    conn.execute(
        """
        INSERT INTO channels (source_id, name, external_id, url, metadata_json)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_id, external_id) DO UPDATE SET
            name = excluded.name,
            url = excluded.url,
            metadata_json = excluded.metadata_json
        """,
        (source_id, name, external_id, url, _json_dumps(metadata)),
    )
    row = conn.execute(
        "SELECT id FROM channels WHERE source_id = ? AND external_id IS ?",
        (source_id, external_id),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def upsert_user(
    conn: sqlite3.Connection,
    source_id: int,
    external_id: str,
    handle: Optional[str],
    display_name: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    conn.execute(
        """
        INSERT INTO users (source_id, external_id, handle, display_name, metadata_json)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_id, external_id) DO UPDATE SET
            handle = excluded.handle,
            display_name = excluded.display_name,
            metadata_json = excluded.metadata_json
        """,
        (source_id, external_id, handle, display_name, _json_dumps(metadata)),
    )
    row = conn.execute(
        "SELECT id FROM users WHERE source_id = ? AND external_id = ?",
        (source_id, external_id),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def fetch_message_by_external_id(
    conn: sqlite3.Connection,
    source_id: int,
    external_id: str,
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM messages WHERE source_id = ? AND external_id = ?",
        (source_id, external_id),
    ).fetchone()


def record_message_version(
    conn: sqlite3.Connection,
    message_id: int,
    content: Optional[str],
    content_raw: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO message_versions (message_id, captured_at, content, content_raw, metadata_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            message_id,
            datetime.utcnow().isoformat(),
            content,
            content_raw,
            _json_dumps(metadata),
        ),
    )
    conn.commit()


def upsert_message(
    conn: sqlite3.Connection,
    source_id: int,
    channel_id: int,
    external_id: str,
    author_id: Optional[int],
    content: Optional[str],
    content_raw: Optional[str],
    created_at: Optional[str],
    edited_at: Optional[str],
    thread_root_external_id: Optional[str],
    reply_to_external_id: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[int, bool, bool]:
    existing = fetch_message_by_external_id(conn, source_id, external_id)
    edited = False
    if existing is not None:
        if (existing["content"] != content) or (existing["content_raw"] != content_raw):
            record_message_version(
                conn,
                int(existing["id"]),
                existing["content"],
                existing["content_raw"],
                {"previous_metadata": existing["metadata_json"]},
            )
            edited = True
        conn.execute(
            """
            UPDATE messages SET
                author_id = COALESCE(?, author_id),
                content = COALESCE(?, content),
                content_raw = COALESCE(?, content_raw),
                edited_at = COALESCE(?, edited_at),
                thread_root_external_id = COALESCE(?, thread_root_external_id),
                reply_to_external_id = COALESCE(?, reply_to_external_id),
                metadata_json = COALESCE(?, metadata_json)
            WHERE id = ?
            """,
            (
                author_id,
                content,
                content_raw,
                edited_at,
                thread_root_external_id,
                reply_to_external_id,
                _json_dumps(metadata),
                int(existing["id"]),
            ),
        )
        conn.commit()
        return int(existing["id"]), False, edited

    conn.execute(
        """
        INSERT INTO messages (
            source_id, channel_id, external_id, author_id,
            thread_root_external_id, reply_to_external_id,
            content, content_raw, created_at, edited_at, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            channel_id,
            external_id,
            author_id,
            thread_root_external_id,
            reply_to_external_id,
            content,
            content_raw,
            created_at,
            edited_at,
            _json_dumps(metadata),
        ),
    )
    row = conn.execute(
        "SELECT id FROM messages WHERE source_id = ? AND external_id = ?",
        (source_id, external_id),
    ).fetchone()
    conn.commit()
    return int(row["id"]), True, edited


def upsert_reaction(
    conn: sqlite3.Connection,
    message_id: int,
    emoji: str,
    count: int,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO reactions (message_id, emoji, count, metadata_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(message_id, emoji) DO UPDATE SET
            count = excluded.count,
            metadata_json = excluded.metadata_json
        """,
        (message_id, emoji, count, _json_dumps(metadata)),
    )
    conn.commit()


def record_event(
    conn: sqlite3.Connection,
    source_id: int,
    channel_id: Optional[int],
    message_id: Optional[int],
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO events (source_id, channel_id, message_id, type, created_at, payload_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            channel_id,
            message_id,
            event_type,
            datetime.utcnow().isoformat(),
            _json_dumps(payload),
        ),
    )
    conn.commit()


def get_sync_state(
    conn: sqlite3.Connection,
    source_id: int,
    channel_id: int,
) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM sync_state WHERE source_id = ? AND channel_id = ?",
        (source_id, channel_id),
    ).fetchone()
    if row:
        return row
    conn.execute(
        """
        INSERT INTO sync_state (source_id, channel_id, mode, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (source_id, channel_id, "recent", datetime.utcnow().isoformat()),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM sync_state WHERE source_id = ? AND channel_id = ?",
        (source_id, channel_id),
    ).fetchone()


def update_sync_state(
    conn: sqlite3.Connection,
    source_id: int,
    channel_id: int,
    mode: str,
    last_seen_at: Optional[str],
    oldest_seen_at: Optional[str],
    cursor: Optional[Dict[str, Any]],
    idle_cycles: int,
) -> None:
    conn.execute(
        """
        UPDATE sync_state SET
            mode = ?,
            last_seen_at = ?,
            oldest_seen_at = ?,
            cursor_json = ?,
            idle_cycles = ?,
            updated_at = ?
        WHERE source_id = ? AND channel_id = ?
        """,
        (
            mode,
            last_seen_at,
            oldest_seen_at,
            _json_dumps(cursor),
            idle_cycles,
            datetime.utcnow().isoformat(),
            source_id,
            channel_id,
        ),
    )
    conn.commit()
