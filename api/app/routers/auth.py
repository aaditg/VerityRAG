from __future__ import annotations

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.utils.oauth import build_oauth_url

router = APIRouter(prefix='/auth/google')


@router.get('/login')
def google_login(state: str = 'state-placeholder') -> dict:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_redirect_uri:
        raise HTTPException(status_code=500, detail='google auth not configured')
    url = build_oauth_url(
        'https://accounts.google.com/o/oauth2/v2/auth',
        {
            'client_id': settings.google_client_id,
            'redirect_uri': settings.google_redirect_uri,
            'response_type': 'code',
            'scope': 'openid email profile',
            'access_type': 'offline',
            'prompt': 'consent',
            'state': state,
        },
    )
    return {'auth_url': url}


@router.get('/callback')
async def google_callback(code: str, state: str) -> dict:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret or not settings.google_redirect_uri:
        raise HTTPException(status_code=500, detail='google auth not configured')

    data = {
        'code': code,
        'client_id': settings.google_client_id,
        'client_secret': settings.google_client_secret,
        'redirect_uri': settings.google_redirect_uri,
        'grant_type': 'authorization_code',
    }
    async with httpx.AsyncClient(timeout=20) as client:
        token_resp = await client.post('https://oauth2.googleapis.com/token', data=data)
        token_resp.raise_for_status()
        token_json = token_resp.json()
    # TODO: link Google identity to existing Slack identity via user_identities mapping.
    return {'state': state, 'token_received': bool(token_json.get('access_token'))}
