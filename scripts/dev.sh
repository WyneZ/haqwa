#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

if [[ ! -d web/frontend/node_modules ]]; then
  npm --prefix web/frontend ci
fi

VITE_USE_MOCK=false npm --prefix web/frontend run build
exec uv run uvicorn web.api.main:app --port 8000
