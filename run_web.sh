#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$PROJECT_DIR/portal.log"
PID_FILE="$PROJECT_DIR/portal.pid"
URL="http://127.0.0.1:8501"

cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

if [ ! -x ".venv/bin/streamlit" ]; then
  source .venv/bin/activate
  pip install -r requirements.txt
fi

if lsof -nP -iTCP:8501 -sTCP:LISTEN >/dev/null 2>&1; then
  open "$URL"
  exit 0
fi

nohup .venv/bin/streamlit run app.py --server.headless true --server.address 127.0.0.1 --server.port 8501 >"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"

for _ in $(seq 1 20); do
  if lsof -nP -iTCP:8501 -sTCP:LISTEN >/dev/null 2>&1; then
    open "$URL"
    exit 0
  fi
  sleep 1
done

echo "Portal failed to start. Check log: $LOG_FILE" >&2
exit 1
