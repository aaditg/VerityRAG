#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/api"
source .venv/bin/activate

export PYTHONPATH="$ROOT_DIR/api"
export DATABASE_URL='postgresql+psycopg://postgres:postgres@127.0.0.1:5432/rag'
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
export AWS_REGION=us-east-1
export AWS_ENDPOINT_URL=http://localhost:4566
export SQS_SYNC_QUEUE_URL=http://localhost:4566/000000000000/rag-sync
export OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-http://127.0.0.1:11434}
export OLLAMA_MODEL=${OLLAMA_MODEL:-llama3.1:8b}
export OLLAMA_EMBED_MODEL=${OLLAMA_EMBED_MODEL:-nomic-embed-text}
export OLLAMA_TIMEOUT_SECONDS=${OLLAMA_TIMEOUT_SECONDS:-45}
export IGNORED_SOURCE_NAME_PATTERNS=${IGNORED_SOURCE_NAME_PATTERNS:-*readme*,*license*,*changelog*,.ds_store,*q1 enterprise notes*}

exec uvicorn app.main:app --reload --port 8000
