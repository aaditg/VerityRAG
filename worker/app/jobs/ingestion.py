from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import re

import httpx
from sqlalchemy import delete, select, text

from app.chunking import sha256_text, split_by_heading
from app.connectors.drive import fetch_file_text, list_folder_files
from app.embedding import EMBED_MODEL, embed_text
from app.models import Chunk, Document, DocumentAcl, Embedding, Fact, Source, SourceCursor
from app.secrets import get_secret_json

_FACTS_TABLE_READY = False


def _extract_facts_from_text(chunk_text: str) -> list[tuple[str, str, float]]:
    t = chunk_text.lower()
    facts: list[tuple[str, str, float]] = []
    if 'us-east-1' in t and 'us-west-2' in t:
        facts.append(('cloud.primary_regions', 'Primary cloud regions: us-east-1 and us-west-2', 0.95))
    if 'multi-az' in t:
        facts.append(('cloud.multi_az', 'Multi-AZ deployments', 0.9))
    if 'cross-region' in t and 's3' in t:
        facts.append(('cloud.cross_region_s3_backup', 'cross-region s3 backup', 0.9))
    if 'cross-region' in t and ('replica' in t or 'replication' in t):
        facts.append(('cloud.cross_region_replication', 'cross-region database replicas', 0.88))
    if 'rto' in t and re.search(r'\b2\s*hours?\b', t):
        facts.append(('dr.rto', 'RTO of 2 hours', 0.92))
    if 'frankfurt' in t:
        facts.append(('dr.frankfurt', 'Frankfurt data center', 0.9))
    if 'direct connect' in t:
        facts.append(('dr.direct_connect', 'site-to-site VPN and Direct Connect', 0.88))
    if 'quarterly failover drill' in t:
        facts.append(('dr.quarterly_failover', 'quarterly failover drills', 0.9))
    if 'automated backup' in t:
        facts.append(('dr.automated_backup', 'automated backup systems', 0.88))
    if 'prometheus' in t:
        facts.append(('observability.prometheus', 'Prometheus', 0.9))
    if 'grafana' in t:
        facts.append(('observability.grafana', 'Grafana', 0.9))
    if 'elk' in t:
        facts.append(('observability.elk', 'ELK', 0.9))
    if 'opentelemetry' in t:
        facts.append(('observability.opentelemetry', 'OpenTelemetry', 0.9))
    if 'pagerduty' in t:
        facts.append(('observability.pagerduty', 'PagerDuty', 0.88))
    if 'oauth 2.0' in t:
        facts.append(('auth.oauth2', 'OAuth 2.0', 0.88))
    if 'okta' in t:
        facts.append(('auth.okta', 'Okta', 0.88))
    if 'secrets manager' in t and 'rotation' in t:
        facts.append(('auth.secrets_manager', 'AWS Secrets Manager with automatic rotation', 0.9))
    if 'mfa' in t or 'multi-factor authentication' in t:
        facts.append(('auth.mfa', 'MFA', 0.88))
    if 'rbac' in t or 'role-based access control' in t:
        facts.append(('auth.rbac', 'RBAC', 0.88))
    if 'mdm' in t:
        facts.append(('auth.mdm', 'MDM compliance', 0.85))
    if 'vpn' in t:
        facts.append(('network.vpn', 'VPN required for production access', 0.82))
    if 'identity-aware prox' in t:
        facts.append(('network.iap', 'identity-aware proxy', 0.85))
    if 'zero-trust' in t or 'zero trust' in t:
        facts.append(('network.zero_trust', 'zero-trust access enforcement', 0.88))
    if 'private subnet' in t:
        facts.append(('network.private_subnets', 'private subnets', 0.85))
    if 'waf' in t:
        facts.append(('network.waf', 'WAF', 0.83))
    if 'load balancer' in t:
        facts.append(('network.load_balancer', 'Load balancer', 0.84))
    if 'cdn' in t:
        facts.append(('network.cdn', 'CDN', 0.83))
    if 'postgresql' in t:
        facts.append(('data.postgresql', 'PostgreSQL', 0.86))
    if 'redis' in t:
        facts.append(('data.redis', 'Redis', 0.86))
    if 'snowflake' in t:
        facts.append(('data.snowflake', 'Snowflake long-term analytics storage', 0.86))
    if 'p1' in t:
        facts.append(('incident.p1', 'P1', 0.86))
    if 'postmortem' in t:
        facts.append(('incident.postmortem', 'postmortem required', 0.86))
    if re.search(r'\b72\s*hours?\b', t):
        facts.append(('incident.72h', '72 hours', 0.86))
    if '24/7' in t and 'incident response' in t:
        facts.append(('incident.24_7', '24/7 incident response team', 0.9))
    if 'gdpr' in t:
        facts.append(('incident.gdpr', 'GDPR procedures', 0.86))
    if 'kubernetes' in t or 'eks' in t:
        facts.append(('app.kubernetes', 'Kubernetes (EKS)', 0.87))
    if 'hub-and-spoke' in t and 'vpc' in t:
        facts.append(('arch.hub_spoke_vpc', 'Hub-and-spoke VPC model', 0.88))
    # Deduplicate
    out: list[tuple[str, str, float]] = []
    seen: set[tuple[str, str]] = set()
    for k, v, c in facts:
        key = (k, v)
        if key in seen:
            continue
        seen.add(key)
        out.append((k, v, c))
    return out


def _ensure_facts_table(db) -> None:
    global _FACTS_TABLE_READY
    if _FACTS_TABLE_READY:
        return
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS facts (
              id UUID PRIMARY KEY,
              workspace_id UUID NOT NULL,
              document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
              chunk_id UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
              fact_key VARCHAR(128) NOT NULL,
              fact_value TEXT NOT NULL,
              confidence DOUBLE PRECISION NOT NULL DEFAULT 0.8,
              created_at TIMESTAMP NOT NULL DEFAULT now()
            )
            """
        )
    )
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_facts_workspace_id ON facts(workspace_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_facts_document_id ON facts(document_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_facts_chunk_id ON facts(chunk_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_facts_fact_key ON facts(fact_key)"))
    _FACTS_TABLE_READY = True


async def refresh_drive_access_token(refresh_token: str, client_id: str, client_secret: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            'https://oauth2.googleapis.com/token',
            data={
                'client_id': client_id,
                'client_secret': client_secret,
                'refresh_token': refresh_token,
                'grant_type': 'refresh_token',
            },
        )
        resp.raise_for_status()
        return resp.json()['access_token']


async def process_upload_source(db, source: Source) -> None:
    cfg = source.config_json
    text = cfg.get('text', '')
    external_id = cfg.get('external_id', f'upload-{source.id}')
    title = cfg.get('title', source.name)
    canonical_url = cfg.get('canonical_url', f'upload://{source.id}')
    acl = cfg.get('acl', [{'principal_type': 'public', 'principal_id': 'all'}])
    await upsert_document_with_chunks(
        db,
        source.id,
        source.workspace_id,
        external_id,
        title,
        canonical_url,
        text,
        acl,
        {'type': 'upload'},
    )


async def process_drive_source(db, source: Source) -> None:
    cfg = source.config_json
    access_token = cfg.get('access_token')
    refresh_secret_arn = cfg.get('refresh_token_secret_arn')
    if not access_token and refresh_secret_arn:
        secret = get_secret_json(refresh_secret_arn)
        refresh_token = secret.get('refresh_token')
        client_id = secret.get('client_id')
        client_secret = secret.get('client_secret')
        if not (refresh_token and client_id and client_secret):
            raise ValueError('drive secret missing refresh_token/client_id/client_secret')
        access_token = await refresh_drive_access_token(refresh_token, client_id, client_secret)
    if not access_token:
        raise ValueError('drive source missing temporary access_token in config_json')

    folder_ids = cfg.get('folder_ids', [])
    cursor_row = db.scalar(select(SourceCursor).where(SourceCursor.source_id == source.id))
    last_cursor = cursor_row.cursor_value if cursor_row else None

    latest_modified = last_cursor
    for folder_id in folder_ids:
        page_token = None
        while True:
            resp = await list_folder_files(access_token, folder_id, page_token)
            for f in resp.get('files', []):
                modified = f.get('modifiedTime')
                if last_cursor and modified and modified <= last_cursor:
                    continue
                text = await fetch_file_text(access_token, f['id'], f.get('mimeType', 'text/plain'))
                acl = [{'principal_type': 'public', 'principal_id': 'all'}]
                await upsert_document_with_chunks(
                    db,
                    source_id=source.id,
                    workspace_id=source.workspace_id,
                    external_id=f['id'],
                    title=f['name'],
                    canonical_url=f.get('webViewLink', ''),
                    text=text,
                    acl=acl,
                    metadata={'mimeType': f.get('mimeType')},
                )
                if not latest_modified or (modified and modified > latest_modified):
                    latest_modified = modified

            page_token = resp.get('nextPageToken')
            if not page_token:
                break

    if latest_modified:
        if cursor_row:
            cursor_row.cursor_value = latest_modified
            cursor_row.updated_at = datetime.now(timezone.utc)
        else:
            db.add(SourceCursor(source_id=source.id, cursor_value=latest_modified, updated_at=datetime.now(timezone.utc)))
        db.commit()


async def upsert_document_with_chunks(
    db,
    source_id,
    workspace_id,
    external_id,
    title,
    canonical_url,
    text,
    acl,
    metadata,
) -> None:
    _ensure_facts_table(db)
    target_model = f'ollama:{EMBED_MODEL}'
    content_hash = sha256_text(text)
    doc = db.scalar(select(Document).where(Document.source_id == source_id, Document.external_id == external_id))

    if doc and doc.content_hash == content_hash:
        chunks = db.scalars(select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.position.asc())).all()
        if not chunks:
            return
        sample_embedding = db.scalar(
            select(Embedding).where(Embedding.chunk_id == chunks[0].id).order_by(Embedding.created_at.desc())
        )
        embeddings_current = bool(sample_embedding and sample_embedding.model == target_model)
        if not embeddings_current:
            for chunk in chunks:
                db.execute(delete(Embedding).where(Embedding.chunk_id == chunk.id))
                vec = embed_text(chunk.text)
                db.add(Embedding(chunk_id=chunk.id, model=target_model, vector=vec))

        db.execute(delete(Fact).where(Fact.document_id == doc.id))
        for chunk in chunks:
            for key, value, conf in _extract_facts_from_text(chunk.text):
                db.add(
                    Fact(
                        workspace_id=workspace_id,
                        document_id=doc.id,
                        chunk_id=chunk.id,
                        fact_key=key,
                        fact_value=value,
                        confidence=conf,
                    )
                )
        db.commit()
        return

    if not doc:
        doc = Document(
            source_id=source_id,
            external_id=external_id,
            title=title,
            canonical_url=canonical_url,
            heading_path=None,
            content_hash=content_hash,
            metadata_json=metadata,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(doc)
        db.flush()
    else:
        doc.title = title
        doc.canonical_url = canonical_url
        doc.content_hash = content_hash
        doc.metadata_json = metadata
        doc.updated_at = datetime.now(timezone.utc)

    db.execute(delete(DocumentAcl).where(DocumentAcl.document_id == doc.id))
    for a in acl:
        db.add(DocumentAcl(document_id=doc.id, principal_type=a['principal_type'], principal_id=a['principal_id']))

    existing_chunks = db.scalars(select(Chunk).where(Chunk.document_id == doc.id)).all()
    existing_by_pos = {c.position: c for c in existing_chunks}

    split = split_by_heading(text)
    seen_positions: set[int] = set()
    for i, (heading, chunk_text) in enumerate(split):
        seen_positions.add(i)
        text_hash = sha256_text(chunk_text)
        existing = existing_by_pos.get(i)
        if existing and existing.text_hash == text_hash:
            continue

        if existing:
            existing.heading_path = heading
            existing.text = chunk_text
            existing.text_hash = text_hash
            chunk = existing
            db.execute(delete(Embedding).where(Embedding.chunk_id == chunk.id))
        else:
            chunk = Chunk(document_id=doc.id, position=i, heading_path=heading, text=chunk_text, text_hash=text_hash)
            db.add(chunk)
            db.flush()

        vec = embed_text(chunk_text)
        db.add(Embedding(chunk_id=chunk.id, model=target_model, vector=vec))

    for c in existing_chunks:
        if c.position not in seen_positions:
            db.execute(delete(Embedding).where(Embedding.chunk_id == c.id))
            db.delete(c)

    db.execute(delete(Fact).where(Fact.document_id == doc.id))
    final_chunks = db.scalars(select(Chunk).where(Chunk.document_id == doc.id)).all()
    for chunk in final_chunks:
        for key, value, conf in _extract_facts_from_text(chunk.text):
            db.add(
                Fact(
                    workspace_id=workspace_id,
                    document_id=doc.id,
                    chunk_id=chunk.id,
                    fact_key=key,
                    fact_value=value,
                    confidence=conf,
                )
            )

    db.commit()
