from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Citation(BaseModel):
    document_id: UUID
    title: str
    url: str
    heading_path: str | None = None
    chunk_id: UUID


class AskRequest(BaseModel):
    user_id: UUID
    tenant_id: UUID
    workspace_id: UUID
    persona: str
    query: str
    technical_depth: str = 'medium'
    conversationalness: float = 0.5
    output_tone: str = 'direct'
    conciseness: float = 0.6
    use_general_knowledge: bool = True
    fast_mode: bool = False
    session_id: str | None = None
    use_context: bool = True
    filters: dict[str, Any] | None = None
    explain: bool = False


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    confidence: float
    suggested_followups: list[str] = Field(default_factory=list)
    cache_hit: bool = False
    mode: str = 'grounded'


class SourceCreateRequest(BaseModel):
    workspace_id: UUID
    connector_type: str
    name: str
    config: dict[str, Any] = Field(default_factory=dict)


class SourceCreateResponse(BaseModel):
    source_id: UUID


class SyncRequest(BaseModel):
    job_type: str


class SourceStatusResponse(BaseModel):
    source_id: UUID
    latest_job_status: str | None
    latest_job_error: str | None
