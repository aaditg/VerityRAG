#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import fnmatch
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = os.environ.get('RAG_API_BASE', 'http://127.0.0.1:8000')
TENANT_ID = os.environ.get('RAG_TENANT_ID', '11111111-1111-1111-1111-111111111111')
WORKSPACE_ID = os.environ.get('RAG_WORKSPACE_ID', '22222222-2222-2222-2222-222222222222')
USER_ID = os.environ.get('RAG_USER_ID', '33333333-3333-3333-3333-333333333333')
OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
OLLAMA_VISION_MODEL = os.environ.get('OLLAMA_VISION_MODEL', 'llava:7b')
OLLAMA_VISION_ENABLED = os.environ.get('OLLAMA_VISION_ENABLED', '1') not in {'0', 'false', 'False'}
RAG_IGNORED_PATTERNS = [
    p.strip().lower()
    for p in os.environ.get(
        'RAG_IGNORED_PATTERNS',
        '*readme*,*license*,*changelog*,.ds_store,*q1 enterprise notes*',
    ).split(',')
    if p.strip()
]

TEXT_EXTENSIONS = {
    '.txt', '.md', '.csv', '.json', '.yaml', '.yml', '.log', '.py', '.js', '.ts', '.tsx', '.html', '.css', '.sql'
}
PDF_EXTENSIONS = {'.pdf'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}

GENERAL_KB_ENTRIES = [
    {
        'slug': 'geography_basics',
        'title': 'General Geography Basics',
        'text': (
            '# Geography Basics\n'
            'Earth has seven continents and five major oceans.\n'
            'The Pacific Ocean is the largest ocean.\n'
            'The Nile and the Amazon are among the longest rivers.'
        ),
    },
    {
        'slug': 'time_date_basics',
        'title': 'General Time and Date Basics',
        'text': (
            '# Time Basics\n'
            'UTC stands for Coordinated Universal Time and is the global time reference.\n'
            'Leap years usually occur every 4 years with century exceptions.\n'
            'ISO date format is YYYY-MM-DD.'
        ),
    },
    {
        'slug': 'math_units_basics',
        'title': 'General Math and Units Basics',
        'text': (
            '# Math and Units\n'
            'A kilometer is 1000 meters.\n'
            'A gigabyte in decimal notation is 10^9 bytes.\n'
            'Average is computed as sum divided by count.'
        ),
    },
    {
        'slug': 'security_basics',
        'title': 'General Security Basics',
        'text': (
            '# Security Basics\n'
            'MFA means multi-factor authentication.\n'
            'Encryption at rest protects stored data.\n'
            'Principle of least privilege limits access to only what is necessary.'
        ),
    },
]


def _request(method: str, path: str, body: dict | None = None) -> dict:
    data = None
    headers = {'content-type': 'application/json'}
    if body is not None:
        data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(f'{API_BASE}{path}', data=data, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode('utf-8')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'HTTP {exc.code} {path}: {detail}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Failed to reach API at {API_BASE}: {exc}') from exc


def ask_once(
    persona: str,
    query: str,
    explain: bool = False,
    technical_depth: str = 'medium',
    output_tone: str = 'direct',
    conciseness: float = 0.6,
    fast_mode: bool = False,
    session_id: str | None = None,
    use_context: bool = True,
) -> dict:
    payload = {
        'tenant_id': TENANT_ID,
        'workspace_id': WORKSPACE_ID,
        'user_id': USER_ID,
        'persona': persona,
        'query': query,
        'technical_depth': technical_depth,
        'output_tone': output_tone,
        'conciseness': conciseness,
        'fast_mode': fast_mode,
        'session_id': session_id,
        'use_context': use_context,
        'explain': explain,
    }
    return _request('POST', '/ask', payload)


def print_answer(resp: dict) -> None:
    print('\n=== Answer ===')
    print(resp.get('answer', ''))
    print(f"\nMode: {resp.get('mode')}  Confidence: {resp.get('confidence')}  Cache hit: {resp.get('cache_hit')}")

    citations = resp.get('citations', [])
    if citations:
        print('\n=== Citations ===')
        for i, c in enumerate(citations, start=1):
            title = c.get('title', 'untitled')
            url = c.get('url', '')
            heading = c.get('heading_path') or ''
            suffix = f' ({heading})' if heading else ''
            print(f'{i}. {title}{suffix} -> {url}')

    followups = resp.get('suggested_followups', [])
    if followups:
        print('\n=== Suggested Followups ===')
        for f in followups:
            print(f'- {f}')


def chat_loop(
    persona: str,
    technical_depth: str,
    output_tone: str,
    conciseness: float,
    fast_mode: bool,
    session_id: str | None,
    use_context: bool,
) -> None:
    print(
        f'Chat mode started. Persona={persona} technical_depth={technical_depth} '
        f'output_tone={output_tone} conciseness={conciseness:.2f} fast_mode={fast_mode}. Type "exit" to quit.'
    )
    while True:
        try:
            query = input('\nYou> ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\nExiting chat.')
            return
        if not query:
            continue
        if query.lower() in {'exit', 'quit'}:
            print('Exiting chat.')
            return
        resp = ask_once(
            persona=persona,
            query=query,
            technical_depth=technical_depth,
            output_tone=output_tone,
            conciseness=conciseness,
            fast_mode=fast_mode,
            session_id=session_id,
            use_context=use_context,
        )
        print_answer(resp)


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return (
            f"# {path.name}\n"
            f"PDF file detected at {path}. Install pypdf for text extraction.\n"
            f"TODO: add full PDF parsing pipeline."
        )

    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages[:50]:
            parts.append(page.extract_text() or '')
        text = '\n'.join(parts).strip()
        return text or f'# {path.name}\nPDF contained no extractable text.'
    except Exception as exc:
        return f"# {path.name}\nFailed to parse PDF: {exc}"


def _extract_image_text_with_ollama(path: Path, rel: Path) -> str:
    if not OLLAMA_VISION_ENABLED:
        return (
            f'# {rel.name}\n'
            f'Type: image\n'
            f'Path: {rel}\n'
            'Indexed as metadata only (OLLAMA_VISION_ENABLED=0).'
        )

    try:
        image_b64 = base64.b64encode(path.read_bytes()).decode('utf-8')
        payload = {
            'model': OLLAMA_VISION_MODEL,
            'stream': False,
            'messages': [
                {
                    'role': 'user',
                    'content': (
                        'Extract key text and factual details from this image. '
                        'Return concise plain text with headings and bullet points.'
                    ),
                    'images': [image_b64],
                }
            ],
            'options': {'temperature': 0},
        }

        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat",
            data=json.dumps(payload).encode('utf-8'),
            method='POST',
            headers={'content-type': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            content = data.get('message', {}).get('content', '').strip()

        if not content:
            content = 'No extractable details returned by vision model.'

        return (
            f'# {rel.name}\n'
            f'Type: image\n'
            f'Path: {rel}\n'
            f'Vision model: {OLLAMA_VISION_MODEL}\n\n'
            f'{content}'
        )
    except Exception as exc:
        return (
            f'# {rel.name}\n'
            f'Type: image\n'
            f'Path: {rel}\n'
            f'Vision extraction failed: {exc}\n'
            'Indexed as metadata fallback.'
        )


def extract_file_text(path: Path, root: Path) -> str | None:
    ext = path.suffix.lower()
    rel = path.relative_to(root)

    if ext in TEXT_EXTENSIONS:
        try:
            return path.read_text(encoding='utf-8', errors='ignore')
        except Exception as exc:
            return f'# {rel}\nFailed to read text file: {exc}'

    if ext in PDF_EXTENSIONS:
        return _extract_pdf_text(path)

    if ext in IMAGE_EXTENSIONS:
        return _extract_image_text_with_ollama(path, rel)

    if ext in VIDEO_EXTENSIONS:
        return (
            f'# {rel.name}\n'
            f'Type: video\n'
            f'Path: {rel}\n'
            'Indexed as metadata only. TODO: transcription pipeline.'
        )

    if ext in AUDIO_EXTENSIONS:
        return (
            f'# {rel.name}\n'
            f'Type: audio\n'
            f'Path: {rel}\n'
            'Indexed as metadata only. TODO: speech-to-text pipeline.'
        )

    return None


def _slugify(value: str) -> str:
    out = re.sub(r'[^a-zA-Z0-9]+', '_', value.strip().lower())
    return out.strip('_') or 'item'


def _is_ignored_path(path: Path) -> bool:
    name = path.name.lower()
    rel = str(path).lower()
    for pattern in RAG_IGNORED_PATTERNS:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel, pattern):
            return True
    return False


def create_upload_source(name: str, external_id: str, title: str, canonical_url: str, text: str) -> str:
    payload = {
        'workspace_id': WORKSPACE_ID,
        'connector_type': 'upload',
        'name': name,
        'config': {
            'external_id': external_id,
            'title': title,
            'canonical_url': canonical_url,
            'text': text,
            'acl': [{'principal_type': 'public', 'principal_id': 'all'}],
        },
    }
    resp = _request('POST', '/sources', payload)
    source_id = resp.get('source_id')
    if not source_id:
        raise RuntimeError(f'Unexpected response from /sources: {resp}')
    return source_id


def enqueue_sync(source_id: str) -> str:
    payload = {'job_type': 'ingest_upload'}
    resp = _request('POST', f'/sources/{source_id}/sync', payload)
    return resp.get('job_id', '')


def wait_for_source(source_id: str, timeout_seconds: int = 60) -> str:
    start = time.time()
    while time.time() - start < timeout_seconds:
        resp = _request('GET', f'/sources/{source_id}/status')
        status = resp.get('latest_job_status')
        if status in {'success', 'failed'}:
            return status
        time.sleep(1.5)
    return 'timeout'


def sync_learnset(folder: Path) -> None:
    if not folder.exists():
        raise RuntimeError(f'Learnset folder not found: {folder}')

    files = [p for p in folder.rglob('*') if p.is_file()]
    if not files:
        print(f'No files found in {folder}')
        return

    indexed = 0
    skipped = 0
    for path in files:
        if _is_ignored_path(path):
            skipped += 1
            print(f'Skipped {path.relative_to(folder)} (ignored)')
            continue

        text = extract_file_text(path, folder)
        if text is None:
            skipped += 1
            continue

        rel = path.relative_to(folder)
        source_name = f'learnset:{rel}'
        external_id = str(rel)
        title = path.name
        canonical_url = f'file://{path}'

        source_id = create_upload_source(source_name, external_id, title, canonical_url, text)
        enqueue_sync(source_id)
        status = wait_for_source(source_id)
        print(f'Indexed {rel} -> source={source_id} status={status}')
        indexed += 1

    print(f'\nDone. Indexed={indexed}, skipped={skipped}, folder={folder}')


def seed_general_kb() -> None:
    seeded = 0
    for entry in GENERAL_KB_ENTRIES:
        slug = _slugify(entry['slug'])
        source_name = f'gkb:{slug}'
        external_id = f'gkb/{slug}'
        title = entry['title']
        canonical_url = f'gkb://{slug}'
        text = entry['text']

        source_id = create_upload_source(source_name, external_id, title, canonical_url, text)
        enqueue_sync(source_id)
        status = wait_for_source(source_id)
        print(f'Seeded {source_name} -> source={source_id} status={status}')
        seeded += 1

    print(f'\nGeneral KB seed complete. Total entries: {seeded}')


def main() -> None:
    parser = argparse.ArgumentParser(description='CLI for local Verity RAG MVP')
    subparsers = parser.add_subparsers(dest='command', required=True)

    ask_parser = subparsers.add_parser('ask', help='Ask one question')
    ask_parser.add_argument('--persona', default='sales', choices=['sales', 'exec', 'engineering'])
    ask_parser.add_argument('--technical-depth', default='medium', choices=['low', 'medium', 'high'])
    ask_parser.add_argument('--output-tone', default='direct', choices=['friendly', 'direct', 'critical'])
    ask_parser.add_argument('--conciseness', type=float, default=0.6)
    ask_parser.add_argument('--fast-mode', action='store_true')
    ask_parser.add_argument('--session-id', default='cli-default')
    ask_parser.add_argument('--no-context', action='store_true')
    ask_parser.add_argument('query')

    chat_parser = subparsers.add_parser('chat', help='Interactive chat loop')
    chat_parser.add_argument('--persona', default='sales', choices=['sales', 'exec', 'engineering'])
    chat_parser.add_argument('--technical-depth', default='medium', choices=['low', 'medium', 'high'])
    chat_parser.add_argument('--output-tone', default='direct', choices=['friendly', 'direct', 'critical'])
    chat_parser.add_argument('--conciseness', type=float, default=0.6)
    chat_parser.add_argument('--fast-mode', action='store_true')
    chat_parser.add_argument('--session-id', default='cli-chat')
    chat_parser.add_argument('--no-context', action='store_true')

    learnset_parser = subparsers.add_parser('learnset', help='Learnset operations')
    learnset_sub = learnset_parser.add_subparsers(dest='learnset_cmd', required=True)
    sync_parser = learnset_sub.add_parser('sync', help='Index files in learnset folder')
    sync_parser.add_argument('--path', default='learnset', help='Folder to ingest')

    gkb_parser = subparsers.add_parser('gkb', help='General knowledge operations')
    gkb_sub = gkb_parser.add_subparsers(dest='gkb_cmd', required=True)
    gkb_sub.add_parser('seed', help='Seed lightweight general knowledge dataset')

    args = parser.parse_args()

    if args.command == 'ask':
        resp = ask_once(
            persona=args.persona,
            query=args.query,
            technical_depth=args.technical_depth,
            output_tone=args.output_tone,
            conciseness=max(0.0, min(1.0, float(args.conciseness))),
            fast_mode=bool(args.fast_mode),
            session_id=args.session_id,
            use_context=not bool(args.no_context),
        )
        print_answer(resp)
        return

    if args.command == 'chat':
        chat_loop(
            persona=args.persona,
            technical_depth=args.technical_depth,
            output_tone=args.output_tone,
            conciseness=max(0.0, min(1.0, float(args.conciseness))),
            fast_mode=bool(args.fast_mode),
            session_id=args.session_id,
            use_context=not bool(args.no_context),
        )
        return

    if args.command == 'learnset' and args.learnset_cmd == 'sync':
        sync_learnset(Path(args.path).resolve())
        return

    if args.command == 'gkb' and args.gkb_cmd == 'seed':
        seed_general_kb()
        return

    parser.print_help()


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
