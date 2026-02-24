"""add facts table"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002_add_facts_table'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'facts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('chunks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('fact_key', sa.String(128), nullable=False),
        sa.Column('fact_value', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False, server_default=sa.text('0.8')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_facts_workspace_id', 'facts', ['workspace_id'])
    op.create_index('ix_facts_document_id', 'facts', ['document_id'])
    op.create_index('ix_facts_chunk_id', 'facts', ['chunk_id'])
    op.create_index('ix_facts_fact_key', 'facts', ['fact_key'])


def downgrade() -> None:
    op.drop_index('ix_facts_fact_key', table_name='facts')
    op.drop_index('ix_facts_chunk_id', table_name='facts')
    op.drop_index('ix_facts_document_id', table_name='facts')
    op.drop_index('ix_facts_workspace_id', table_name='facts')
    op.drop_table('facts')
