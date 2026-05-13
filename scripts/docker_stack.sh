#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${DOCKER_ENV_FILE:-${ROOT_DIR}/.env.docker}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing Docker env file: ${ENV_FILE}" >&2
  echo "Create it from .env.docker.example first." >&2
  exit 1
fi

cmd="${1:-up}"
shift || true

compose=(docker compose --env-file "${ENV_FILE}" -f "${ROOT_DIR}/docker-compose.yml")

case "${cmd}" in
  up)
    "${compose[@]}" up -d --build "$@"
    ;;
  down)
    "${compose[@]}" down "$@"
    ;;
  restart)
    "${compose[@]}" restart "$@"
    ;;
  logs)
    "${compose[@]}" logs -f --tail=200 "$@"
    ;;
  ps)
    "${compose[@]}" ps "$@"
    ;;
  *)
    echo "Usage: $0 {up|down|restart|logs|ps} [compose args...]" >&2
    exit 1
    ;;
esac
