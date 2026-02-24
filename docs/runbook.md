# Runbook

## Local Bring-Up (Simple)
1. `cd "/Users/aadit/Downloads/Verity"`
2. `make setup`
3. `make api` (terminal A)
4. `make worker` (terminal B)
5. `make demo` (terminal C)

## CLI Usage
- Ask once:
```bash
make ask Q="Summarize pipeline and risks"
```
- Interactive session:
```bash
make chat
```
- Index learnset folder:
```bash
make learnset-sync
```

## Learnset Folder
- Path: `/Users/aadit/Downloads/Verity/learnset`
- Drop files and run `make learnset-sync`
- Supported now:
  - Text-like files (full text)
  - PDFs (via `pypdf`)
  - Images/video/audio (metadata-only placeholder indexing)

## Manual Bring-Up (Detailed)
1. `./scripts/setup_local.sh`
2. API: `./scripts/run_api.sh`
3. Worker: `./scripts/run_worker.sh`
4. Demo: `./scripts/vertical_slice_demo.sh`

## Operational Checks
- `/health` must return `{"status":"ok"}`.
- `sync_jobs` transitions: `queued -> running -> success/failed`.
- `answer_cache` hit should flip response `cache_hit=true` on repeated ask.
- ACL check: remove matching `document_acl` row, answer should stop citing document.

## Incident Basics
- Worker failures: inspect `sync_jobs.error` and worker logs.
- Retrieval gaps: inspect `document_acl`, `chunks`, `embeddings` cardinality.
- High cost: inspect cache hit rates in Redis keys and table misses.

Image parsing via Ollama vision (optional):
```bash
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_VISION_MODEL=llava:7b
export OLLAMA_VISION_ENABLED=1
```
