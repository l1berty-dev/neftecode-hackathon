#!/usr/bin/env sh
set -eu

command=${1:-up}
case "$command" in
  up)
    docker compose up --build --wait
    printf '%s\n' 'Dashboard: http://127.0.0.1:8080'
    ;;
  down)
    docker compose down
    ;;
  reset)
    docker compose down --volumes
    ;;
  *)
    printf '%s\n' 'Usage: ./scripts/demo.sh {up|down|reset}' >&2
    exit 2
    ;;
esac
