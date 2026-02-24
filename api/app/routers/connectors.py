from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Connector, ConnectorAccount, ConnectorCredential, ConnectorType, Source, SourceType, Workspace
from app.db.session import get_db
from app.services.secrets_service import store_connector_secret
from app.utils.oauth import build_oauth_url

router = APIRouter()


class LookerConfigRequest(BaseModel):
    workspace_id: str
    base_url: str
    client_id: str
    client_secret_secret_arn: str


class NotionConfigRequest(BaseModel):
    workspace_id: str
    token_secret_arn: str


class DriveConfigureRequest(BaseModel):
    workspace_id: str
    folder_ids: list[str]
    refresh_token_secret_arn: str | None = None
    access_token: str | None = None


@router.get('/oauth/salesforce/login')
def salesforce_login(state: str = 'state-placeholder') -> dict:
    # TODO: populate from tenant connector config.
    return {'auth_url': f'https://login.salesforce.com/services/oauth2/authorize?state={state}'}


@router.get('/oauth/salesforce/callback')
def salesforce_callback(code: str, state: str) -> dict:
    # TODO: exchange code for refresh token and store secret ARN in connector_credentials.
    return {'status': 'stub', 'code': code[:8], 'state': state}


@router.get('/oauth/github/callback')
def github_callback(installation_id: int, setup_action: str | None = None) -> dict:
    # TODO: persist GitHub App installation_id in connector_accounts.
    return {'status': 'stub', 'installation_id': installation_id, 'setup_action': setup_action}


@router.post('/connectors/looker/configure')
def looker_configure(req: LookerConfigRequest, db: Session = Depends(get_db)) -> dict:
    try:
        workspace_uuid = UUID(req.workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid workspace_id') from exc
    ws = db.scalar(select(Workspace).where(Workspace.id == workspace_uuid))
    if not ws:
        raise HTTPException(status_code=404, detail='workspace not found')
    connector = Connector(workspace_id=ws.id, connector_type=ConnectorType.looker, name='Looker')
    db.add(connector)
    db.flush()
    account = ConnectorAccount(connector_id=connector.id, external_account_id=req.client_id, metadata_json={'base_url': req.base_url})
    db.add(account)
    db.flush()
    db.add(ConnectorCredential(connector_account_id=account.id, secret_arn=req.client_secret_secret_arn))
    db.commit()
    return {'status': 'configured'}


@router.post('/connectors/looker/test')
def looker_test() -> dict:
    # TODO: exchange API3 credentials for access token and validate API reachability.
    return {'status': 'stub', 'detail': 'implement /login token exchange'}


@router.get('/oauth/google-drive/login')
def drive_login(state: str = 'state-placeholder') -> dict:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_drive_redirect_uri:
        raise HTTPException(status_code=500, detail='google drive oauth not configured')
    url = build_oauth_url(
        'https://accounts.google.com/o/oauth2/v2/auth',
        {
            'client_id': settings.google_client_id,
            'redirect_uri': settings.google_drive_redirect_uri,
            'response_type': 'code',
            'scope': 'https://www.googleapis.com/auth/drive.readonly',
            'access_type': 'offline',
            'prompt': 'consent',
            'state': state,
        },
    )
    return {'auth_url': url}


@router.get('/oauth/google-drive/callback')
async def drive_callback(code: str, state: str) -> dict:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret or not settings.google_drive_redirect_uri:
        raise HTTPException(status_code=500, detail='google drive oauth not configured')

    data = {
        'code': code,
        'client_id': settings.google_client_id,
        'client_secret': settings.google_client_secret,
        'redirect_uri': settings.google_drive_redirect_uri,
        'grant_type': 'authorization_code',
    }
    async with httpx.AsyncClient(timeout=20) as client:
        token_resp = await client.post('https://oauth2.googleapis.com/token', data=data)
        token_resp.raise_for_status()
        token_json = token_resp.json()

    refresh_token = token_json.get('refresh_token')
    if not refresh_token:
        raise HTTPException(status_code=400, detail='no refresh token returned; use consent prompt')

    secret_arn = store_connector_secret(
        {
            'refresh_token': refresh_token,
            'client_id': settings.google_client_id,
            'client_secret': settings.google_client_secret,
        },
        name_hint='google-drive-refresh',
    )
    return {'status': 'connected', 'state': state, 'refresh_token_secret_arn': secret_arn}


@router.post('/connectors/drive/configure')
def drive_configure(req: DriveConfigureRequest, db: Session = Depends(get_db)) -> dict:
    try:
        workspace_uuid = UUID(req.workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid workspace_id') from exc
    ws = db.scalar(select(Workspace).where(Workspace.id == workspace_uuid))
    if not ws:
        raise HTTPException(status_code=404, detail='workspace not found')

    connector = Connector(workspace_id=ws.id, connector_type=ConnectorType.drive, name='Google Drive')
    db.add(connector)
    db.flush()
    account = ConnectorAccount(connector_id=connector.id, external_account_id='google-drive-account', metadata_json={})
    db.add(account)
    db.flush()
    if req.refresh_token_secret_arn:
        db.add(ConnectorCredential(connector_account_id=account.id, secret_arn=req.refresh_token_secret_arn))

    source = Source(
        workspace_id=ws.id,
        connector_type=SourceType.drive,
        name='Google Drive Source',
        config_json={
            'folder_ids': req.folder_ids,
            'refresh_token_secret_arn': req.refresh_token_secret_arn,
            'access_token': req.access_token,
        },
        status='active',
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return {'status': 'configured', 'source_id': str(source.id)}


@router.post('/connectors/notion/configure')
def notion_configure(req: NotionConfigRequest, db: Session = Depends(get_db)) -> dict:
    try:
        workspace_uuid = UUID(req.workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid workspace_id') from exc
    ws = db.scalar(select(Workspace).where(Workspace.id == workspace_uuid))
    if not ws:
        raise HTTPException(status_code=404, detail='workspace not found')
    connector = Connector(workspace_id=ws.id, connector_type=ConnectorType.notion, name='Notion')
    db.add(connector)
    db.flush()
    account = ConnectorAccount(connector_id=connector.id, external_account_id='notion-workspace', metadata_json={})
    db.add(account)
    db.flush()
    db.add(ConnectorCredential(connector_account_id=account.id, secret_arn=req.token_secret_arn))
    db.commit()
    return {'status': 'configured'}
