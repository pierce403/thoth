#!/usr/bin/env bash
set -euo pipefail

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

"$PYTHON_BIN" -m thoth.agent "$@"
