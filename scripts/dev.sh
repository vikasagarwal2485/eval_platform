#!/usr/bin/env bash
# Start the backend (uvicorn --reload, :8000) and the frontend (vite, :5173) together.
# Ctrl-C stops both. Open http://localhost:5173 (the dev server proxies /api to the backend).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"

cleanup() { trap - EXIT INT TERM; kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd "$ROOT/backend" && exec .venv/bin/uvicorn app.main:app_factory --factory --reload --port "$BACKEND_PORT") &
(cd "$ROOT/frontend" && VITE_BACKEND_URL="http://localhost:$BACKEND_PORT" exec npm run dev) &
wait
