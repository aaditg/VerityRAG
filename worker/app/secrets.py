from __future__ import annotations

import json

import boto3

from app.config import get_settings

settings = get_settings()


def get_secret_json(secret_arn: str) -> dict:
    if secret_arn.startswith('local://'):
        # local://{"refresh_token":"..."}
        return json.loads(secret_arn[len('local://'):])
    client = boto3.client('secretsmanager', region_name=settings.aws_region)
    resp = client.get_secret_value(SecretId=secret_arn)
    return json.loads(resp['SecretString'])
