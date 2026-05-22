#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-}"
if [ -z "$ROLE" ]; then
  echo "Usage: scripts/run-role.sh <role> [message...]" >&2
  exit 1
fi
shift || true

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
CONFIG_FILE="$ROOT_DIR/config/generated/$ROLE.config.json"

if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

node "$ROOT_DIR/scripts/generate-nanobot-configs.mjs" >/dev/null

if [ ! -f "$CONFIG_FILE" ]; then
  echo "Unknown role or missing generated config: $ROLE" >&2
  exit 1
fi

if [ "$#" -gt 0 ]; then
  "$ROOT_DIR/nanobot/.venv/bin/nanobot" agent --config "$CONFIG_FILE" --message "$*"
else
  "$ROOT_DIR/nanobot/.venv/bin/nanobot" agent --config "$CONFIG_FILE"
fi
