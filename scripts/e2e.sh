#!/usr/bin/env bash
# Boot the app on a throwaway SQLite DB (built SPA served by FastAPI), run Playwright, shut down.
#   scripts/e2e.sh            (expects .venv, frontend/dist and e2e/node_modules)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="$ROOT/.venv/Scripts/python"
PORT="${E2E_PORT:-8765}"
DB_DIR="$(mktemp -d)"
cd "$ROOT/backend"
DATABASE_URL="sqlite:///$DB_DIR/e2e.db" APP_TODAY=2026-11-18 LOG_JSON=0 PYTHONUTF8=1 \
  "$PY" -m uvicorn app.main:app --port "$PORT" > "$DB_DIR/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 1 90); do curl -sf "http://localhost:$PORT/readyz" >/dev/null && break; sleep 1; done
curl -sf "http://localhost:$PORT/readyz" >/dev/null || { cat "$DB_DIR/server.log"; exit 1; }
cd "$ROOT/e2e"
BASE_URL="http://localhost:$PORT" npx playwright test "$@"
