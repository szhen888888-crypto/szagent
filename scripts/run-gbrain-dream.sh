#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KNOWLEDGE_DIR="$ROOT_DIR/knowledge"
ENV_FILE="$ROOT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

if [ -n "${GBRAIN_EMBED_API_KEY:-}" ]; then
  export OPENAI_API_KEY="$GBRAIN_EMBED_API_KEY"
fi
export OPENAI_BASE_URL="${GBRAIN_EMBED_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}"
export GBRAIN_EMBED_MODEL="${GBRAIN_EMBED_MODEL:-text-embedding-v4}"
export GBRAIN_EMBED_DIMENSIONS="${GBRAIN_EMBED_DIMENSIONS:-1536}"
export GBRAIN_EMBED_BATCH_SIZE="${GBRAIN_EMBED_BATCH_SIZE:-10}"

if ! command -v gbrain >/dev/null 2>&1; then
  echo "gbrain CLI not found" >&2
  exit 1
fi

if [ ! -d "$KNOWLEDGE_DIR" ]; then
  echo "Knowledge directory not found: $KNOWLEDGE_DIR" >&2
  exit 1
fi

if [ "${1:-}" = "--full" ]; then
  shift
  exec gbrain dream --dir "$ROOT_DIR" "$@"
fi

if [ "${1:-}" = "--sync-first" ]; then
  shift
  "$ROOT_DIR/scripts/sync-gbrain-knowledge.sh"
fi

if [ "${1:-}" = "--phase" ]; then
  exec gbrain dream --dir "$KNOWLEDGE_DIR" "$@"
fi

# Safe default for this repo: shared knowledge is synced by
# scripts/sync-gbrain-knowledge.sh into inyourday/... slugs. Upstream `sync`
# would import every Markdown file in the repo, so skip it unless --full is used.
for phase in lint backlinks extract embed orphans; do
  gbrain dream --dir "$KNOWLEDGE_DIR" --phase "$phase" "$@"
done
