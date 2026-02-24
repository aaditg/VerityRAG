#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "python3.12 is required. Install with: brew install python@3.12"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker Desktop and ensure 'docker' is on PATH."
  exit 1
fi

PY_CHECK="import sys; assert sys.version_info >= (3, 12), 'Python 3.12+ required'"
python3.12 -c "$PY_CHECK"

echo "[1/6] Starting docker services..."
docker compose up -d postgres redis localstack

echo "[2/6] Ensuring localstack resources..."
docker compose exec -T localstack awslocal sqs create-queue --queue-name rag-sync >/dev/null || true
docker compose exec -T localstack awslocal s3 mb s3://rag-artifacts-local >/dev/null || true

echo "[3/6] Setting up API virtualenv..."
cd "$ROOT_DIR/api"
[ -f .env ] || cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
pip install -r requirements.txt
export PYTHONPATH="$ROOT_DIR/api"
export DATABASE_URL='postgresql+psycopg://postgres:postgres@127.0.0.1:5432/rag'
alembic upgrade head
deactivate

echo "[4/6] Setting up Worker virtualenv..."
cd "$ROOT_DIR/worker"
[ -f .env ] || cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
pip install -r requirements.txt
deactivate

echo "[5/6] Seeding demo data..."
cd "$ROOT_DIR"
./scripts/seed_local.sh

echo "[6/6] Setup complete."
echo "Run API:    ./scripts/run_api.sh"
echo "Run Worker: ./scripts/run_worker.sh"
echo "Test demo:  ./scripts/vertical_slice_demo.sh"
