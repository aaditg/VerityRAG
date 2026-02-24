from __future__ import annotations

import json

import boto3

from app.config import get_settings


settings = get_settings()


def enqueue_sync_job(payload: dict) -> None:
    if not settings.sqs_sync_queue_url:
        return
    client = boto3.client('sqs', region_name=settings.aws_region, endpoint_url=settings.aws_endpoint_url)
    client.send_message(QueueUrl=settings.sqs_sync_queue_url, MessageBody=json.dumps(payload))
