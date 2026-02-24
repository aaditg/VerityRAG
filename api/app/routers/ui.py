from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import JobStatus, JobType, Source, SourceType, SyncJob, Workspace
from app.db.session import get_db
from app.queue.sqs_client import enqueue_sync_job

router = APIRouter()

ROOT_DIR = Path(__file__).resolve().parents[3]
UI_HTML = ROOT_DIR / 'api' / 'app' / 'ui' / 'index.html'
LEARNSET_DIR = ROOT_DIR / 'learnset'
TEXT_EXTENSIONS = {
    '.txt', '.md', '.csv', '.json', '.yaml', '.yml', '.log', '.py', '.js', '.ts', '.tsx', '.html', '.css', '.sql'
}
PDF_EXTENSIONS = {'.pdf'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}


def _safe_name(name: str) -> str:
    base = Path(name).name
    clean = re.sub(r'[^a-zA-Z0-9._-]+', '_', base).strip('._')
    return clean or 'upload.bin'


def _is_ignored_file(path: Path) -> bool:
    settings = get_settings()
    patterns = [p.strip().lower() for p in settings.ignored_source_name_patterns.split(',') if p.strip()]
    name = path.name.lower()
    rel = str(path).lower()
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(rel, p) for p in patterns)


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return f'# {path.name}\nPDF file detected. Install pypdf for text extraction.'
    try:
        reader = PdfReader(str(path))
        text = '\n'.join((page.extract_text() or '') for page in reader.pages[:50]).strip()
        return text or f'# {path.name}\nPDF contained no extractable text.'
    except Exception as exc:
        return f'# {path.name}\nFailed to parse PDF: {exc}'


def _extract_file_text(path: Path, root: Path) -> str | None:
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
        return f'# {rel.name}\nType: image\nPath: {rel}\nIndexed as metadata only.'
    if ext in VIDEO_EXTENSIONS:
        return f'# {rel.name}\nType: video\nPath: {rel}\nIndexed as metadata only.'
    if ext in AUDIO_EXTENSIONS:
        return f'# {rel.name}\nType: audio\nPath: {rel}\nIndexed as metadata only.'
    return None


@router.get('/ui')
def ui_page() -> FileResponse:
    if not UI_HTML.exists():
        raise HTTPException(status_code=404, detail='ui file not found')
    return FileResponse(UI_HTML)


@router.get('/ui/files')
def list_files() -> JSONResponse:
    LEARNSET_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for p in sorted(LEARNSET_DIR.rglob('*')):
        if p.is_file():
            rel = p.relative_to(LEARNSET_DIR)
            files.append({'name': rel.name, 'path': str(rel), 'size': p.stat().st_size})
    return JSONResponse({'count': len(files), 'files': files})


@router.post('/ui/upload')
async def upload_files(files: list[UploadFile] = File(...)) -> JSONResponse:
    LEARNSET_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for file in files:
        filename = _safe_name(file.filename or 'upload.bin')
        target = LEARNSET_DIR / filename
        i = 1
        while target.exists():
            stem = Path(filename).stem
            suffix = Path(filename).suffix
            target = LEARNSET_DIR / f'{stem}_{i}{suffix}'
            i += 1
        data = await file.read()
        target.write_bytes(data)
        saved.append({'name': target.name, 'size': len(data), 'path': str(target.relative_to(LEARNSET_DIR))})
    return JSONResponse({'saved_count': len(saved), 'saved': saved, 'learnset_path': str(LEARNSET_DIR)})


@router.post('/ui/learnset/sync')
def sync_learnset(
    body: dict = Body(default_factory=dict),
    db: Session = Depends(get_db),
) -> JSONResponse:
    workspace_id = body.get('workspace_id', '22222222-2222-2222-2222-222222222222')
    try:
        ws_uuid = UUID(str(workspace_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid workspace_id') from exc

    ws = db.scalar(select(Workspace).where(Workspace.id == ws_uuid))
    if not ws:
        raise HTTPException(status_code=404, detail='workspace not found')

    LEARNSET_DIR.mkdir(parents=True, exist_ok=True)
    files = [p for p in LEARNSET_DIR.rglob('*') if p.is_file()]
    queued = 0
    skipped = 0
    jobs: list[dict] = []

    for path in files:
        if _is_ignored_file(path):
            skipped += 1
            continue

        text = _extract_file_text(path, LEARNSET_DIR)
        if text is None:
            skipped += 1
            continue

        rel = path.relative_to(LEARNSET_DIR)
        source_name = f'learnset:{rel}'
        config = {
            'external_id': str(rel),
            'title': path.name,
            'canonical_url': f'file://{path}',
            'text': text,
            'acl': [{'principal_type': 'public', 'principal_id': 'all'}],
        }

        source = db.scalar(
            select(Source).where(
                Source.workspace_id == ws.id,
                Source.connector_type == SourceType.upload,
                Source.name == source_name,
            )
        )
        if source:
            source.config_json = config
            source.status = 'active'
        else:
            source = Source(
                workspace_id=ws.id,
                connector_type=SourceType.upload,
                name=source_name,
                config_json=config,
                status='active',
            )
            db.add(source)
            db.flush()

        job = SyncJob(source_id=source.id, job_type=JobType.ingest_upload, status=JobStatus.queued, payload_json={})
        db.add(job)
        db.flush()
        enqueue_sync_job({'job_id': str(job.id), 'source_id': str(source.id), 'job_type': 'ingest_upload'})

        queued += 1
        jobs.append({'job_id': str(job.id), 'source_id': str(source.id), 'source_name': source_name})

    db.commit()
    return JSONResponse(
        {
            'learnset_path': str(LEARNSET_DIR),
            'queued_jobs': queued,
            'skipped_files': skipped,
            'jobs': jobs[:100],
        }
    )
