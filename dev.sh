#!/usr/bin/env bash
# Dev mode: Flask API with auto-reload on :5055 + Vite with hot reload on :5173. Open :5173.
cd "$(dirname "$0")"
[ -d frontend/node_modules ] || (cd frontend && npm install)
lsof -ti :5055 | xargs kill 2>/dev/null
(cd backend && ADDGATE_DEV=1 ../.venv/bin/gunicorn -k gthread --threads 32 -w 1 -b 127.0.0.1:5055 --timeout 300 --reload app:app) &
trap "kill $!" EXIT
cd frontend && npm run dev -- --open
