#!/usr/bin/env bash
set -euo pipefail

LOOP_DELAY="${THOTH_LOOP_DELAY:-20}"
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

while true; do
  "$PYTHON_BIN" -m thoth.sync "$@"
  sleep "$LOOP_DELAY"
done
