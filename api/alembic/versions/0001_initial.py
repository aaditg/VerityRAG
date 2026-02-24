"""initial schema"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector;')

    op.create_table('tenants',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table('workspaces',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table('users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('email', sa.String(320), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table('user_identities',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider', sa.String(64), nullable=False),
        sa.Column('provider_user_id', sa.String(255), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('provider', 'provider_user_id', name='uq_identity_provider_user'),
    )
    op.create_table('groups',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('external_group_id', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
    )
    op.create_table('group_memberships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('group_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('group_id', 'user_id', name='uq_group_user'),
    )

    op.create_table('personas',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('key', sa.String(64), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table('persona_rules',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('persona_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('personas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('retrieval_filter', sa.JSON(), nullable=False),
        sa.Column('tool_allowlist', sa.JSON(), nullable=False),
        sa.Column('output_template', sa.Text(), nullable=False),
        sa.Column('safety_rules', sa.JSON(), nullable=False),
        sa.Column('cache_ttl_seconds', sa.Integer(), nullable=False),
    )
    op.create_table('persona_defaults',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('persona_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('personas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('key', sa.String(64), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
    )
    op.create_table('sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('connector_type', postgresql.ENUM('upload','drive','notion','github','salesforce','looker', name='source_type'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('config_json', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table('documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('external_id', sa.String(255), nullable=False),
        sa.Column('title', sa.String(1024), nullable=False),
        sa.Column('canonical_url', sa.String(2048), nullable=False),
        sa.Column('heading_path', sa.String(1024), nullable=True),
        sa.Column('content_hash', sa.String(128), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('source_id', 'external_id', name='uq_source_external_doc'),
    )
    op.create_table('document_tags',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tag', sa.String(128), nullable=False),
    )
    op.create_table('document_acl',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('principal_type', sa.String(16), nullable=False),
        sa.Column('principal_id', sa.String(255), nullable=False),
    )
    op.create_table('chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('heading_path', sa.String(1024), nullable=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('text_hash', sa.String(128), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('document_id', 'position', name='uq_chunk_doc_position'),
    )
    op.create_table('embeddings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('chunk_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('chunks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('model', sa.String(128), nullable=False),
        sa.Column('vector', Vector(256), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table('chunk_tags',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('chunk_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('chunks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tag', sa.String(128), nullable=False),
    )
    op.create_table('connectors',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('connector_type', postgresql.ENUM('salesforce','looker','github','drive','notion', name='connector_type'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table('connector_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('connector_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('connectors.id', ondelete='CASCADE'), nullable=False),
        sa.Column('external_account_id', sa.String(255), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=False),
    )
    op.create_table('connector_credentials',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('connector_account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('connector_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('secret_arn', sa.String(1024), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )

    op.create_table('source_cursors',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sources.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('cursor_value', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_table('sync_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sources.id', ondelete='CASCADE'), nullable=True),
        sa.Column('job_type', postgresql.ENUM('ingest_upload','sync_drive','sync_notion','refresh_salesforce','refresh_looker_tiles','refresh_github_index', name='job_type'), nullable=False),
        sa.Column('status', postgresql.ENUM('queued','running','success','failed', name='job_status'), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )

    op.create_table('tool_cache',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('cache_key', sa.String(512), nullable=False, unique=True),
        sa.Column('value_json', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
    )
    op.create_table('answer_cache',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('cache_key', sa.String(512), nullable=False, unique=True),
        sa.Column('answer_json', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
    )

    op.create_table('audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action', sa.String(128), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table('feedback',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('answer_cache_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('answer_cache.id', ondelete='SET NULL'), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    for table in [
        'feedback', 'audit_logs', 'answer_cache', 'tool_cache', 'sync_jobs', 'source_cursors',
        'connector_credentials', 'connector_accounts', 'connectors', 'chunk_tags', 'embeddings',
        'chunks', 'document_acl', 'document_tags', 'documents', 'sources', 'persona_defaults',
        'persona_rules', 'personas', 'group_memberships', 'groups', 'user_identities', 'users',
        'workspaces', 'tenants'
    ]:
        op.drop_table(table)
    op.execute('DROP TYPE IF EXISTS job_status')
    op.execute('DROP TYPE IF EXISTS job_type')
    op.execute('DROP TYPE IF EXISTS connector_type')
    op.execute('DROP TYPE IF EXISTS source_type')
