#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$PROJECT_DIR/portal.pid"

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE")"
  if kill "$PID" >/dev/null 2>&1; then
    rm -f "$PID_FILE"
    exit 0
  fi
fi

PORT_PID="$(lsof -tiTCP:8501 -sTCP:LISTEN || true)"
if [ -n "$PORT_PID" ]; then
  kill "$PORT_PID"
fi

rm -f "$PID_FILE"
