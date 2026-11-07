#!/usr/bin/env bash
# Starts ADDGate at http://localhost:5055. First run sets up a Python venv.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "First run: setting up Python environment..."
  python3 -m venv .venv
  .venv/bin/pip install -q -r backend/requirements.txt
fi

if [ ! -f backend/static/index.html ]; then
  echo "Building the UI (needs Node)..."
  (cd frontend && npm install && npm run build)
fi

( sleep 1.5 && open "http://localhost:5055" 2>/dev/null || true ) &
cd backend && exec ../.venv/bin/python app.py
