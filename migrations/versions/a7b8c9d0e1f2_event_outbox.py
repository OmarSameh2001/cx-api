"""event outbox

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-15 00:00:00.000000

event_outbox holds events written in the same transaction as their data
(T1.2.1); processed_events records which handler finished which event, so a
handler never runs twice for one event (T1.2.2).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'event_outbox',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('aggregate_type', sa.String(length=32), nullable=False),
        sa.Column('aggregate_id', sa.BigInteger(), nullable=False),
        sa.Column('organisation_id', sa.Integer(), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('available_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_event_outbox_event_type'), 'event_outbox', ['event_type'], unique=False)
    op.create_index(op.f('ix_event_outbox_organisation_id'), 'event_outbox', ['organisation_id'], unique=False)
    op.create_index('ix_event_outbox_aggregate', 'event_outbox', ['aggregate_type', 'aggregate_id'], unique=False)
    op.create_index('ix_event_outbox_pending', 'event_outbox', ['available_at', 'id'], unique=False,
                    postgresql_where=sa.text("status = 'pending'"))
    op.create_table(
        'processed_events',
        sa.Column('event_id', sa.BigInteger(), nullable=False),
        sa.Column('handler', sa.String(length=200), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['event_outbox.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('event_id', 'handler'),
    )


def downgrade() -> None:
    op.drop_table('processed_events')
    op.drop_index('ix_event_outbox_pending', table_name='event_outbox')
    op.drop_index('ix_event_outbox_aggregate', table_name='event_outbox')
    op.drop_index(op.f('ix_event_outbox_organisation_id'), table_name='event_outbox')
    op.drop_index(op.f('ix_event_outbox_event_type'), table_name='event_outbox')
    op.drop_table('event_outbox')
