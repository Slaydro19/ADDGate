#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -d frontend/node_modules ] || (cd frontend && npm install)
lsof -ti :5055 | xargs kill 2>/dev/null
(cd backend && FLASK_DEBUG=1 ../.venv/bin/flask --app app run --port 5055 --reload) &
trap "kill $!" EXIT
cd frontend && npm run dev -- --open
