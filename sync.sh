#!/usr/bin/env bash
set -euo pipefail

LOOP_DELAY="${THOTH_LOOP_DELAY:-20}"

while true; do
  python -m thoth.sync "$@"
  sleep "$LOOP_DELAY"
done
