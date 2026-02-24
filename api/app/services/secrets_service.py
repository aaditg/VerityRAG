from __future__ import annotations

import json
import uuid

import boto3

from app.config import get_settings

settings = get_settings()


def store_connector_secret(payload: dict, name_hint: str) -> str:
    if settings.app_env == 'dev':
        return f"local://{json.dumps(payload)}"

    client = boto3.client('secretsmanager', region_name=settings.aws_region)
    name = f"{settings.secrets_prefix}/{name_hint}-{uuid.uuid4()}"
    resp = client.create_secret(Name=name, SecretString=json.dumps(payload))
    return resp['ARN']
