#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE="$ROOT_DIR/.demo.env"
COMPOSE_FILE="$ROOT_DIR/demo.compose.yaml"

usage() {
  echo "Usage: ./scripts/demo.sh up|down|status|logs"
}

ensure_password() {
  if [ ! -f "$ENV_FILE" ]; then
    password=$(openssl rand -hex 24)
    umask 077
    printf 'POSTGRES_PASSWORD=%s\n' "$password" > "$ENV_FILE"
  fi
}

case "${1:-}" in
  up)
    ensure_password
    echo "Starting Neftecode Advisor. The first start prepares data and trains two models."
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up --build -d --wait
    echo "Ready: http://127.0.0.1:8080"
    ;;
  down)
    ensure_password
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down
    echo "Demo containers removed. Named data/model volumes were preserved."
    ;;
  status)
    ensure_password
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
    ;;
  logs)
    ensure_password
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs --tail=200
    ;;
  *)
    usage
    exit 2
    ;;
esac
