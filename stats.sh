#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="config/thoth.toml"
DB_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG_PATH="$2"
      shift 2
      ;;
    --db)
      DB_OVERRIDE="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [--config path] [--db path]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--config path] [--db path]" >&2
      exit 1
      ;;
  esac
done

PYTHON_BIN="${THOTH_PYTHON:-}"

if [ -z "$PYTHON_BIN" ]; then
  if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
  else
    echo "python not found. Create a venv or set THOTH_PYTHON." >&2
    exit 1
  fi
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

THOTH_REPO_ROOT="$REPO_ROOT" \
THOTH_CONFIG_PATH="$CONFIG_PATH" \
THOTH_DB_OVERRIDE="$DB_OVERRIDE" \
PYTHONPATH="$REPO_ROOT" \
"$PYTHON_BIN" - <<'PY'
import os
import pathlib
import sqlite3
import sys

repo_root = pathlib.Path(os.environ.get("THOTH_REPO_ROOT", ".")).resolve()
config_path = os.environ.get("THOTH_CONFIG_PATH") or "config/thoth.toml"
db_override = os.environ.get("THOTH_DB_OVERRIDE")

sys.path.insert(0, str(repo_root))


def resolve_db_path() -> pathlib.Path:
    if db_override:
        path = pathlib.Path(db_override)
    else:
        try:
            from thoth import config as config_module

            cfg = config_module.load_config(config_path)
            path = pathlib.Path(cfg.db_path)
        except Exception:
            path = pathlib.Path(os.environ.get("THOTH_DB", "data/thoth.db"))
    if not path.is_absolute():
        path = repo_root / path
    return path


def human_size(num: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return bool(row)


def scalar(conn: sqlite3.Connection, query: str) -> int:
    row = conn.execute(query).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


path = resolve_db_path()
print(f"Database: {path}")
if not path.exists():
    print("Database not found.")
    sys.exit(1)

size = path.stat().st_size
print(f"Size: {human_size(size)}")

conn = sqlite3.connect(path)
conn.row_factory = sqlite3.Row

counts = []
for table in [
    "sources",
    "channels",
    "users",
    "messages",
    "message_versions",
    "reactions",
    "events",
    "embeddings",
    "sync_state",
]:
    if table_exists(conn, table):
        counts.append((table, scalar(conn, f"SELECT COUNT(*) FROM {table}")))
    else:
        counts.append((table, 0))

print("\nCounts:")
for name, count in counts:
    print(f"- {name}: {count}")

if table_exists(conn, "messages"):
    row = conn.execute("SELECT MIN(created_at) AS oldest, MAX(created_at) AS newest FROM messages").fetchone()
    oldest = row["oldest"] if row else None
    newest = row["newest"] if row else None
    print("\nMessage time range:")
    print(f"- oldest: {oldest or 'n/a'}")
    print(f"- newest: {newest or 'n/a'}")

if table_exists(conn, "channels") and table_exists(conn, "messages"):
    rows = conn.execute(
        """
        SELECT sources.name AS source, channels.name AS channel, COUNT(messages.id) AS message_count
        FROM messages
        JOIN channels ON channels.id = messages.channel_id
        JOIN sources ON sources.id = messages.source_id
        GROUP BY sources.name, channels.name
        ORDER BY message_count DESC
        LIMIT 10
        """
    ).fetchall()
    if rows:
        print("\nTop channels by message count (top 10):")
        for row in rows:
            print(f"- {row['source']}#{row['channel']}: {row['message_count']}")

conn.close()
PY
