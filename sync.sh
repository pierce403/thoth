#!/usr/bin/env bash
set -euo pipefail

LOOP_DELAY="${THOTH_LOOP_DELAY:-20}"
WATCH_INTERVAL="${THOTH_WATCH_INTERVAL:-2}"
RESTART_ON_CHANGE="${THOTH_RESTART_ON_CHANGE:-1}"
PYTHON_BIN="${THOTH_PYTHON:-}"
CONFIG_PATH=""
PID_FILE="logs/sync.pid"

ARGS=("$@")
for ((i=0; i<${#ARGS[@]}; i++)); do
  if [ "${ARGS[$i]}" = "--config" ] && [ $((i + 1)) -lt ${#ARGS[@]} ]; then
    CONFIG_PATH="${ARGS[$i+1]}"
  fi
done

if [ -z "$CONFIG_PATH" ]; then
  CONFIG_PATH="config/thoth.toml"
fi

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

mkdir -p "$(dirname "$PID_FILE")"
if [ -f "$PID_FILE" ]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" >/dev/null 2>&1; then
    echo "sync.sh already running (pid $EXISTING_PID). Stop it before starting another." >&2
    exit 1
  fi
fi
echo "$$" > "$PID_FILE"

cleanup() {
  if [ -n "${SYNC_PID:-}" ] && kill -0 "$SYNC_PID" >/dev/null 2>&1; then
    kill -INT "$SYNC_PID" >/dev/null 2>&1 || true
    wait "$SYNC_PID" >/dev/null 2>&1 || true
  fi
  rm -f "$PID_FILE"
}

trap cleanup EXIT INT TERM

hash_files() {
  local hash_tool=""
  if command -v sha1sum >/dev/null 2>&1; then
    hash_tool="sha1sum"
  elif command -v shasum >/dev/null 2>&1; then
    hash_tool="shasum -a 1"
  else
    echo ""
    return
  fi

  local paths=()
  if [ -d "thoth" ]; then
    paths+=("thoth")
  fi
  if [ -d "config" ]; then
    paths+=("config")
  fi
  if [ -n "$CONFIG_PATH" ] && [ -f "$CONFIG_PATH" ]; then
    paths+=("$CONFIG_PATH")
  fi

  if [ ${#paths[@]} -eq 0 ]; then
    echo ""
    return
  fi

  find "${paths[@]}" -type f \( -name "*.py" -o -name "*.toml" \) -print0 2>/dev/null \
    | xargs -0 stat -c '%n %Y' 2>/dev/null \
    | eval "$hash_tool" \
    | awk '{print $1}'
}

while true; do
  THOTH_PARENT_PID="$$" "$PYTHON_BIN" -m thoth.sync "$@" &
  SYNC_PID=$!
  RESTART_REASON="exit"

  if [ "$RESTART_ON_CHANGE" = "1" ]; then
    LAST_HASH="$(hash_files)"
    while kill -0 "$SYNC_PID" >/dev/null 2>&1; do
      sleep "$WATCH_INTERVAL"
      NEW_HASH="$(hash_files)"
      if [ -n "$NEW_HASH" ] && [ "$NEW_HASH" != "$LAST_HASH" ]; then
        echo "Code or config changed; restarting sync..." >&2
        kill -INT "$SYNC_PID" >/dev/null 2>&1 || true
        wait "$SYNC_PID" || true
        RESTART_REASON="reload"
        break
      fi
    done
  else
    wait "$SYNC_PID" || true
  fi

  wait "$SYNC_PID" >/dev/null 2>&1 || true
  EXIT_CODE=$?
  if [ "$EXIT_CODE" -eq 3 ]; then
    echo "Browser closed; stopping sync loop." >&2
    exit 0
  fi
  if [ "$EXIT_CODE" -eq 4 ]; then
    echo "Parent sync process missing; stopping sync loop." >&2
    exit 0
  fi
  if [ "$RESTART_REASON" = "reload" ]; then
    sleep "$LOOP_DELAY"
    continue
  fi

  sleep "$LOOP_DELAY"
done
