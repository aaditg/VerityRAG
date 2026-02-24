from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID

import boto3
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.jobs.ingestion import process_drive_source, process_upload_source
from app.models import JobStatus, JobType, Source, SyncJob
from app.runtime import ensure_supported_python


settings = get_settings()
ensure_supported_python()


async def process_job_message(message: dict) -> None:
    body = json.loads(message['Body'])
    job_id = UUID(body['job_id'])

    with SessionLocal() as db:
        job = db.scalar(select(SyncJob).where(SyncJob.id == job_id))
        if not job:
            return
        job.status = JobStatus.running
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

        try:
            source = db.scalar(select(Source).where(Source.id == job.source_id)) if job.source_id else None
            if job.job_type == JobType.ingest_upload:
                if not source:
                    raise ValueError('source missing')
                await process_upload_source(db, source)
            elif job.job_type == JobType.sync_drive:
                if not source:
                    raise ValueError('source missing')
                await process_drive_source(db, source)
            elif job.job_type in {
                JobType.sync_notion,
                JobType.refresh_salesforce,
                JobType.refresh_looker_tiles,
                JobType.refresh_github_index,
            }:
                # TODO: implement non-drive connectors after core RAG baseline is stable.
                pass
            else:
                raise ValueError(f'unsupported job_type={job.job_type}')

            job.status = JobStatus.success
            job.error = None
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as exc:
            job.status = JobStatus.failed
            job.error = str(exc)
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
            raise


def run() -> None:
    if not settings.sqs_sync_queue_url:
        raise RuntimeError('SQS_SYNC_QUEUE_URL is required for worker')

    sqs = boto3.client('sqs', region_name=settings.aws_region, endpoint_url=settings.aws_endpoint_url)
    while True:
        resp = sqs.receive_message(
            QueueUrl=settings.sqs_sync_queue_url,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=20,
        )
        messages = resp.get('Messages', [])
        for msg in messages:
            try:
                asyncio.run(process_job_message(msg))
            finally:
                sqs.delete_message(QueueUrl=settings.sqs_sync_queue_url, ReceiptHandle=msg['ReceiptHandle'])


if __name__ == '__main__':
    run()
