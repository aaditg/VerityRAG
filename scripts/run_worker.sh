#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/worker"
source .venv/bin/activate

unset AWS_PROFILE AWS_SESSION_TOKEN AWS_WEB_IDENTITY_TOKEN_FILE AWS_ROLE_ARN
export DATABASE_URL='postgresql+psycopg://postgres:postgres@127.0.0.1:5432/rag'
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
export AWS_REGION=us-east-1
export AWS_ENDPOINT_URL=http://localhost:4566
export SQS_SYNC_QUEUE_URL=http://localhost:4566/000000000000/rag-sync
export OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-http://127.0.0.1:11434}
export OLLAMA_EMBED_MODEL=${OLLAMA_EMBED_MODEL:-nomic-embed-text}
export OLLAMA_TIMEOUT_SECONDS=${OLLAMA_TIMEOUT_SECONDS:-45}

exec python -m app.main
