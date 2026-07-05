#!/bin/sh
# Starts a throwaway planr server and runs the UI<->server e2e suite.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
PORT=8977
PLANR_DB="$TMP/t.db" PLANR_NOTES_DIR="$TMP/n" PLANR_JOURNAL_DIR="$TMP/j" \
  "$ROOT/.venv/bin/python" -m uvicorn main:app --port $PORT \
  --app-dir "$ROOT" >/dev/null 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
for i in $(seq 1 50); do
  curl -sf "http://127.0.0.1:$PORT/api/contexts" >/dev/null 2>&1 && break
  sleep 0.2
done
BASE="http://127.0.0.1:$PORT" node "$ROOT/tests/test_e2e.js"
