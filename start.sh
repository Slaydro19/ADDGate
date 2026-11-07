#!/usr/bin/env bash
# Starts ADDGate at http://localhost:5055. Sets up / updates the Python environment as needed.
set -e
cd "$(dirname "$0")"

# Turn on the repo's pre-commit check (blocks secrets and personal data from being committed).
[ -d .git ] && git config core.hooksPath .githooks 2>/dev/null || true

if [ ! -d .venv ]; then
  echo "First run: setting up Python environment..."
  python3 -m venv .venv
fi

# Reinstall dependencies whenever requirements.txt changes (e.g. after an update).
REQ_HASH=$(shasum backend/requirements.txt | cut -d' ' -f1)
if [ "$(cat .venv/.req-hash 2>/dev/null)" != "$REQ_HASH" ]; then
  echo "Installing Python dependencies..."
  .venv/bin/pip install -q -r backend/requirements.txt
  echo "$REQ_HASH" > .venv/.req-hash
fi

if [ ! -f backend/static/index.html ]; then
  echo "Building the UI (needs Node)..."
  (cd frontend && npm install && npm run build)
fi

( sleep 2 && open "http://localhost:5055" 2>/dev/null || true ) &
echo "ADDGate running at http://localhost:5055  (Ctrl+C to stop)"
# One worker on purpose: terminal tickets and sessions live in memory. Threads handle concurrency.
# Bound to 127.0.0.1 only, so nothing else on your network can reach it.
cd backend && exec ../.venv/bin/gunicorn -k gthread --threads 32 -w 1 -b 127.0.0.1:5055 \
  --timeout 300 --graceful-timeout 5 --log-level warning app:app
