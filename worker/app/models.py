from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SourceType(str, enum.Enum):
    upload = 'upload'
    drive = 'drive'
    notion = 'notion'
    github = 'github'
    salesforce = 'salesforce'
    looker = 'looker'


class JobType(str, enum.Enum):
    ingest_upload = 'ingest_upload'
    sync_drive = 'sync_drive'
    sync_notion = 'sync_notion'
    refresh_salesforce = 'refresh_salesforce'
    refresh_looker_tiles = 'refresh_looker_tiles'
    refresh_github_index = 'refresh_github_index'


class JobStatus(str, enum.Enum):
    queued = 'queued'
    running = 'running'
    success = 'success'
    failed = 'failed'


class Source(Base):
    __tablename__ = 'sources'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    connector_type: Mapped[SourceType] = mapped_column(Enum(SourceType, name='source_type'))
    name: Mapped[str] = mapped_column(String(255))
    config_json: Mapped[dict] = mapped_column(JSON)


class Document(Base):
    __tablename__ = 'documents'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('sources.id', ondelete='CASCADE'))
    external_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(1024))
    canonical_url: Mapped[str] = mapped_column(String(2048))
    heading_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(128))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocumentAcl(Base):
    __tablename__ = 'document_acl'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('documents.id', ondelete='CASCADE'))
    principal_type: Mapped[str] = mapped_column(String(16))
    principal_id: Mapped[str] = mapped_column(String(255))


class Chunk(Base):
    __tablename__ = 'chunks'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('documents.id', ondelete='CASCADE'))
    position: Mapped[int] = mapped_column()
    heading_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Embedding(Base):
    __tablename__ = 'embeddings'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('chunks.id', ondelete='CASCADE'))
    model: Mapped[str] = mapped_column(String(128), default='deterministic-hash-v1')
    vector: Mapped[list[float]] = mapped_column(Vector(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Fact(Base):
    __tablename__ = 'facts'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('documents.id', ondelete='CASCADE'), index=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('chunks.id', ondelete='CASCADE'), index=True)
    fact_key: Mapped[str] = mapped_column(String(128), index=True)
    fact_value: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SourceCursor(Base):
    __tablename__ = 'source_cursors'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('sources.id', ondelete='CASCADE'), unique=True)
    cursor_value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SyncJob(Base):
    __tablename__ = 'sync_jobs'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('sources.id', ondelete='CASCADE'), nullable=True)
    job_type: Mapped[JobType] = mapped_column(Enum(JobType, name='job_type'))
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, name='job_status'))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
