#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Defaults to the local backend port used across this repo.
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8000}"

# Enable auto-reload by default so on-disk code edits take effect without a
# manual restart. Override with: BACKEND_RELOAD=false ./run_backend.sh
export BACKEND_RELOAD="${BACKEND_RELOAD:-true}"

exec "${ROOT_DIR}/scripts/start_backend_local.sh"
