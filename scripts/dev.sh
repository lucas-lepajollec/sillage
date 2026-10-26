#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export CONFIG_DIR="${CONFIG_DIR:-.data}"
export MEDIA_ROOTS="${MEDIA_ROOTS:-/media}"
uv sync --extra dev --extra sync
(cd frontend && npm ci && npm run build)
exec uv run uvicorn sillage.app:create_app --factory --host 127.0.0.1 --port 2499 --no-access-log
