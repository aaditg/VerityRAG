#!/usr/bin/env bash
set -euo pipefail

docker compose up -d postgres redis localstack

if command -v awslocal >/dev/null 2>&1; then
  awslocal sqs create-queue --queue-name rag-sync >/dev/null || true
  awslocal s3 mb s3://rag-artifacts-local >/dev/null || true
fi

echo "Local services are up."
