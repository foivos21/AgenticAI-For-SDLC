#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Defaults to the local backend port used across this repo.
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8000}"

exec "${ROOT_DIR}/scripts/start_backend_local.sh"
