#!/usr/bin/env bash
# Production-style single process: build the SPA, then serve API + UI from FastAPI on one port.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$ROOT/frontend" && npm run build)
cd "$ROOT/backend"
exec .venv/bin/uvicorn app.main:app_factory --factory --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
