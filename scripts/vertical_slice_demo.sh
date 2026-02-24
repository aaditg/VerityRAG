#!/usr/bin/env bash
set -euo pipefail

curl -s -X POST http://localhost:8000/sources/99999999-9999-9999-9999-999999999999/sync \
  -H 'content-type: application/json' \
  -d '{"job_type":"ingest_upload"}'

echo
sleep 2

curl -s -X POST http://localhost:8000/ask \
  -H 'content-type: application/json' \
  -d '{
    "tenant_id":"11111111-1111-1111-1111-111111111111",
    "workspace_id":"22222222-2222-2222-2222-222222222222",
    "user_id":"33333333-3333-3333-3333-333333333333",
    "persona":"sales",
    "query":"Summarize pipeline and risk"
  }'

echo
