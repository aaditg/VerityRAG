# Multi-Persona Faceted RAG MVP

Production-lean monorepo for a Slack-first, ACL-safe RAG platform on AWS.

## Monorepo Layout
- `api/`: FastAPI app (auth, Slack, ask, admin, connectors)
- `worker/`: SQS ingestion and sync worker
- `infra/`: Terraform for AWS deployment
- `docs/`: architecture and runbook
- `scripts/`: local bootstrap and seed data
- `learnset/`: drop-in local files to index into retrieval

## Fastest Local Setup
Requirements:
- Python `3.12+`
- Docker Desktop running

One-time setup:
```bash
cd "<PROJECT_ROOT>"
make setup
```

Run services:
```bash
make api      # terminal A
make worker   # terminal B
make demo     # terminal C (quick validation)
```
Open local web UI:
```bash
http://127.0.0.1:8000/ui
```
UI includes:
- File upload to `learnset/`
- `Sync Learnset` button (queues ingestion jobs)
- Persona selector
- Technicalness, conciseness, tone controls
- `Use general knowledge` toggle

## CLI Usage (No Raw Curl)
Ask one question:
```bash
make ask Q="What are the main pipeline risks?"
```
Tune style depth:
```bash
make ask PERSONA=sales DEPTH=low Q="How is production access controlled?"
make ask PERSONA=engineering DEPTH=high Q="How is production access controlled?"
```

Interactive chat:
```bash
make chat
```
With custom persona/depth:
```bash
make chat PERSONA=exec DEPTH=medium
```

Sync files from `learnset/` into RAG:
```bash
make learnset-sync
```

Then ask again with `make ask` or `make chat`.

## Learnset Folder
- Put files into `<PROJECT_ROOT>/learnset`.
- Current support:
  - Text-like files (`.txt`, `.md`, `.csv`, `.json`, `.py`, etc.)
  - PDFs (`.pdf`) via `pypdf`
  - Images (`.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.webp`, `.tiff`) via Ollama vision extraction
  - Video/audio currently indexed as metadata placeholders (filename/path) with TODO markers for transcription.
  - Ignore patterns are configurable with `RAG_IGNORED_PATTERNS` (default: `*readme*,*license*,*changelog*,.ds_store,*q1 enterprise notes*`)

## Python Version Enforcement
- Setup script checks for `python3.12`.
- API/worker enforce Python `3.12+` at runtime and fail fast otherwise.

Image parsing via Ollama vision (optional):
```bash
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_VISION_MODEL=llava:7b
export OLLAMA_VISION_ENABLED=1
export RAG_IGNORED_PATTERNS="*readme*,*license*,*changelog*,.ds_store,*q1 enterprise notes*"
```
