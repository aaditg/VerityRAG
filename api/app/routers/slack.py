from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Form
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import User, UserIdentity
from app.db.session import get_db
from app.schemas import AskRequest
from app.services.ask_service import answer_query

router = APIRouter(prefix='/slack')


def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


def _button_block() -> list[dict]:
    return [
        {
            'type': 'actions',
            'elements': [
                {'type': 'button', 'text': {'type': 'plain_text', 'text': 'Client-safe'}, 'value': 'client_safe'},
                {'type': 'button', 'text': {'type': 'plain_text', 'text': 'Slide bullets'}, 'value': 'slide_bullets'},
                {'type': 'button', 'text': {'type': 'plain_text', 'text': 'Exec summary'}, 'value': 'exec_summary'},
                {'type': 'button', 'text': {'type': 'plain_text', 'text': 'Technical deep dive'}, 'value': 'tech_deep_dive'},
                {'type': 'button', 'text': {'type': 'plain_text', 'text': 'Show sources'}, 'value': 'show_sources'},
            ],
        }
    ]


@router.post('/commands')
async def slack_commands(
    text: str = Form(default=''),
    user_id: str = Form(default=''),
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict:
    # TODO: validate Slack signature with SLACK_SIGNING_SECRET.
    slack_identity = db.scalar(
        select(UserIdentity).where(
            UserIdentity.provider == 'slack',
            UserIdentity.provider_user_id == user_id,
        )
    )
    if not slack_identity:
        return {'response_type': 'ephemeral', 'text': 'Slack user is not linked. Contact admin.'}

    google_identity = db.scalar(
        select(UserIdentity).where(
            UserIdentity.user_id == slack_identity.user_id,
            UserIdentity.provider == 'google',
        )
    )
    if not google_identity:
        signin_url = f"/auth/google/login?state=slack-link-{user_id}"
        return {'response_type': 'ephemeral', 'text': f'Please sign in with Google: {signin_url}'}

    parts = text.strip().split(' ', 1)
    if len(parts) < 2:
        return {'response_type': 'ephemeral', 'text': 'Usage: /ask <persona> <question>'}

    persona, question = parts
    user = db.scalar(select(User).where(User.id == slack_identity.user_id))
    if not user:
        return {'response_type': 'ephemeral', 'text': 'Linked user not found.'}

    workspace_id = google_identity.metadata_json.get('workspace_id') or slack_identity.metadata_json.get('workspace_id')
    if not workspace_id:
        return {'response_type': 'ephemeral', 'text': 'Missing workspace mapping on user identity metadata.'}

    try:
        workspace_uuid = UUID(workspace_id)
    except ValueError:
        return {'response_type': 'ephemeral', 'text': 'Invalid workspace mapping for linked identity.'}

    ask_req = AskRequest(
        user_id=user.id,
        tenant_id=user.tenant_id,
        workspace_id=workspace_uuid,
        persona=persona,
        query=question,
    )
    answer = answer_query(db=db, redis=redis, req=ask_req)
    citation_lines = '\n'.join([f"- {c.title}: {c.url}" for c in answer.citations[:5]])

    return {
        'response_type': 'in_channel',
        'text': f"{answer.answer}\n\nSources:\n{citation_lines if citation_lines else '- none'}",
        'blocks': _button_block(),
    }


@router.post('/events')
async def slack_events(body: dict) -> dict:
    # TODO: implement URL verification and event dispatch.
    return {'ok': True, 'received': body.get('type')}


@router.post('/interactive')
async def slack_interactive(payload: str = Form(default='')) -> dict:
    # TODO: map button interactions to persona-specific rewrites.
    return {'ok': True, 'payload': payload}
