#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Force local API targets by default (no remote dependency).
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-5173}"
export VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://127.0.0.1:8000}"
export VITE_PIPELINE_API_BASE_URL="${VITE_PIPELINE_API_BASE_URL:-http://127.0.0.1:8000}"

exec "${ROOT_DIR}/scripts/start_frontend_local.sh"
