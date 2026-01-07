import sqlite3
from typing import List, Dict, Any


def search_messages(conn: sqlite3.Connection, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT messages.content, messages.created_at, channels.name AS channel, sources.name AS source
        FROM messages
        JOIN channels ON channels.id = messages.channel_id
        JOIN sources ON sources.id = messages.source_id
        WHERE messages.content LIKE ?
        ORDER BY messages.created_at DESC
        LIMIT ?
        """,
        (f"%{query}%", limit),
    ).fetchall()
    return [dict(row) for row in rows]


def recent_activity(conn: sqlite3.Connection, limit: int = 5) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT messages.content, messages.created_at, channels.name AS channel, sources.name AS source
        FROM messages
        JOIN channels ON channels.id = messages.channel_id
        JOIN sources ON sources.id = messages.source_id
        ORDER BY messages.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def channel_counts(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT sources.name AS source, channels.name AS channel, COUNT(messages.id) AS message_count
        FROM messages
        JOIN channels ON channels.id = messages.channel_id
        JOIN sources ON sources.id = messages.source_id
        GROUP BY sources.name, channels.name
        ORDER BY message_count DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]
