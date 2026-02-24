from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import JobStatus, JobType, Source, SourceType, SyncJob, Workspace
from app.db.session import get_db
from app.queue.sqs_client import enqueue_sync_job
from app.schemas import SourceCreateRequest, SourceCreateResponse, SourceStatusResponse, SyncRequest

router = APIRouter()


@router.post('/sources', response_model=SourceCreateResponse)
def create_source(req: SourceCreateRequest, db: Session = Depends(get_db)) -> SourceCreateResponse:
    ws = db.scalar(select(Workspace).where(Workspace.id == req.workspace_id))
    if not ws:
        raise HTTPException(status_code=404, detail='workspace not found')

    connector_type = SourceType(req.connector_type)

    # Upsert by workspace+name+connector to avoid learnset duplication on repeated syncs.
    existing = db.scalar(
        select(Source).where(
            Source.workspace_id == ws.id,
            Source.name == req.name,
            Source.connector_type == connector_type,
        )
    )
    if existing:
        existing.config_json = req.config
        existing.status = 'active'
        db.commit()
        db.refresh(existing)
        return SourceCreateResponse(source_id=existing.id)

    source = Source(
        workspace_id=ws.id,
        connector_type=connector_type,
        name=req.name,
        config_json=req.config,
        status='active',
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return SourceCreateResponse(source_id=source.id)


@router.post('/sources/{source_id}/sync')
def sync_source(source_id: str, req: SyncRequest, db: Session = Depends(get_db)) -> dict:
    try:
        source_uuid = UUID(source_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid source_id') from exc
    source = db.scalar(select(Source).where(Source.id == source_uuid))
    if not source:
        raise HTTPException(status_code=404, detail='source not found')

    job = SyncJob(source_id=source.id, job_type=JobType(req.job_type), status=JobStatus.queued, payload_json={})
    db.add(job)
    db.commit()
    db.refresh(job)

    enqueue_sync_job({'job_id': str(job.id), 'source_id': str(source.id), 'job_type': req.job_type})
    return {'job_id': str(job.id), 'status': 'queued'}


@router.get('/sources/{source_id}/status', response_model=SourceStatusResponse)
def source_status(source_id: str, db: Session = Depends(get_db)) -> SourceStatusResponse:
    try:
        source_uuid = UUID(source_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid source_id') from exc
    source = db.scalar(select(Source).where(Source.id == source_uuid))
    if not source:
        raise HTTPException(status_code=404, detail='source not found')
    job = db.scalar(select(SyncJob).where(SyncJob.source_id == source.id).order_by(desc(SyncJob.created_at)).limit(1))
    return SourceStatusResponse(
        source_id=source.id,
        latest_job_status=job.status.value if job else None,
        latest_job_error=job.error if job else None,
    )
