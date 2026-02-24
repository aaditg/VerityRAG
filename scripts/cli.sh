#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/api"

if [ ! -f .venv/bin/python ]; then
  echo "API virtualenv not found. Run: make setup"
  exit 1
fi

source .venv/bin/activate
cd "$ROOT_DIR"
exec python ./scripts/rag_cli.py "$@"
