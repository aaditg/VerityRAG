from fastapi import APIRouter, Body, Depends, HTTPException
from redis import Redis
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.schemas import AskRequest, AskResponse
from app.services.ask_service import answer_query

router = APIRouter()


def get_redis() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


@router.post('/ask', response_model=AskResponse)
def ask(req: AskRequest, db: Session = Depends(get_db), redis: Redis = Depends(get_redis)) -> AskResponse:
    try:
        return answer_query(db=db, redis=redis, req=req)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post('/ask/context/reset')
def reset_context(
    body: dict = Body(default_factory=dict),
    redis: Redis = Depends(get_redis),
) -> dict:
    workspace_id = str(body.get('workspace_id', '')).strip()
    user_id = str(body.get('user_id', '')).strip()
    persona = str(body.get('persona', '')).strip() or 'sales'
    session_id = str(body.get('session_id', '')).strip()
    if not workspace_id or not user_id:
        raise HTTPException(status_code=400, detail='workspace_id and user_id are required')
    sid = session_id or f'{user_id}:{persona}'
    key = f'ctx:{workspace_id}:{user_id}:{persona}:{sid}'
    redis.delete(key)
    return {'ok': True, 'session_id': sid}
