from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import String, and_, cast, literal, or_, select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, DocumentAcl, Embedding, GroupMembership


@dataclass
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    source_id: UUID
    title: str
    url: str
    heading_path: str | None
    text: str
    score: float


def _distance_to_score(distance: float) -> float:
    score = 1.0 - (distance / 2.0)
    return max(0.0, min(1.0, score))


def retrieve_acl_safe(
    db: Session,
    query_vector: list[float],
    user_id: UUID,
    user_email: str,
    top_k: int,
    source_ids: list[UUID] | None = None,
) -> list[RetrievedChunk]:
    group_ids_subq = select(cast(GroupMembership.group_id, String)).where(GroupMembership.user_id == user_id)

    acl_exists = (
        select(literal(1))
        .where(DocumentAcl.document_id == Document.id)
        .where(
            or_(
                and_(DocumentAcl.principal_type == 'user', DocumentAcl.principal_id == str(user_id)),
                and_(DocumentAcl.principal_type == 'email', DocumentAcl.principal_id == user_email),
                and_(DocumentAcl.principal_type == 'group', DocumentAcl.principal_id.in_(group_ids_subq)),
                and_(DocumentAcl.principal_type == 'public', DocumentAcl.principal_id == 'all'),
            )
        )
        .exists()
    )

    stmt = (
        select(
            Chunk.id.label('chunk_id'),
            Document.id.label('document_id'),
            Document.source_id.label('source_id'),
            Document.title.label('title'),
            Document.canonical_url.label('canonical_url'),
            Chunk.heading_path.label('heading_path'),
            Chunk.text.label('text'),
            (Embedding.vector.cosine_distance(query_vector)).label('distance'),
        )
        .join(Embedding, Embedding.chunk_id == Chunk.id)
        .join(Document, Document.id == Chunk.document_id)
        .where(acl_exists)
        .order_by('distance')
        .limit(top_k)
    )

    if source_ids:
        stmt = stmt.where(Document.source_id.in_(source_ids))

    rows = db.execute(stmt).all()
    results: list[RetrievedChunk] = []
    for row in rows:
        score = _distance_to_score(float(row.distance))
        results.append(
            RetrievedChunk(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                source_id=row.source_id,
                title=row.title,
                url=row.canonical_url,
                heading_path=row.heading_path,
                text=row.text,
                score=score,
            )
        )
    return results
