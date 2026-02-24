# Learnset Folder

Drop files here to be indexed into the local RAG knowledge base.

Supported now:
- Text-like files: `.txt`, `.md`, `.csv`, `.json`, `.yaml`, `.yml`, `.log`, `.py`, `.js`, `.ts`, `.tsx`, `.html`, `.css`, `.sql`
- PDF: `.pdf` (requires optional `pypdf`)
- Images are parsed with Ollama vision when enabled (OLLAMA_VISION_MODEL). Videos/audio are still metadata-only placeholders

Then run:
```bash
cd "/Users/aadit/Downloads/Verity"
make learnset-sync
```

Image parsing via Ollama vision (optional):
```bash
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_VISION_MODEL=llava:7b
export OLLAMA_VISION_ENABLED=1
```
