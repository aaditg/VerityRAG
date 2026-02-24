from __future__ import annotations

import json
from datetime import datetime, timedelta

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnswerCache, ToolCache


class CacheService:
    def __init__(self, redis_client: Redis, db: Session):
        self.redis = redis_client
        self.db = db

    def get_answer(self, key: str) -> dict | None:
        value = self.redis.get(f'answer:{key}')
        if value:
            return json.loads(value)
        row = self.db.scalar(select(AnswerCache).where(AnswerCache.cache_key == key))
        if row and row.expires_at > datetime.utcnow():
            return row.answer_json
        return None

    def set_answer(self, key: str, payload: dict, ttl_seconds: int) -> None:
        self.redis.setex(f'answer:{key}', ttl_seconds, json.dumps(payload))
        expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        existing = self.db.scalar(select(AnswerCache).where(AnswerCache.cache_key == key))
        if existing:
            existing.answer_json = payload
            existing.expires_at = expires_at
        else:
            self.db.add(AnswerCache(cache_key=key, answer_json=payload, expires_at=expires_at))
        self.db.commit()

    def get_tool(self, key: str) -> dict | None:
        value = self.redis.get(f'tool:{key}')
        if value:
            return json.loads(value)
        row = self.db.scalar(select(ToolCache).where(ToolCache.cache_key == key))
        if row and row.expires_at > datetime.utcnow():
            return row.value_json
        return None

    def set_tool(self, key: str, payload: dict, ttl_seconds: int) -> None:
        self.redis.setex(f'tool:{key}', ttl_seconds, json.dumps(payload))
        expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        existing = self.db.scalar(select(ToolCache).where(ToolCache.cache_key == key))
        if existing:
            existing.value_json = payload
            existing.expires_at = expires_at
        else:
            self.db.add(ToolCache(cache_key=key, value_json=payload, expires_at=expires_at))
        self.db.commit()
