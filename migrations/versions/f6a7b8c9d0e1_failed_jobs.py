"""failed jobs log

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-11 00:00:00.000000

Background jobs that run out of retries are logged here (T1.1.4), so the
small Redis plan only ever holds the live queue.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'failed_jobs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('task_id', sa.String(length=64), nullable=False),
        sa.Column('task_name', sa.String(length=200), nullable=False),
        sa.Column('args', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('kwargs', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('retries', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error', sa.Text(), nullable=False),
        sa.Column('traceback', sa.Text(), nullable=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_failed_jobs_task_id'), 'failed_jobs', ['task_id'], unique=False)
    op.create_index(op.f('ix_failed_jobs_task_name'), 'failed_jobs', ['task_name'], unique=False)
    op.create_index(op.f('ix_failed_jobs_failed_at'), 'failed_jobs', ['failed_at'], unique=False)
    # the expiry sweep runs every minute; keep it off a full table scan
    op.create_index(
        'ix_submissions_open_expires_at', 'submissions', ['expires_at'],
        unique=False, postgresql_where=sa.text("status = 'in_progress'"),
    )


def downgrade() -> None:
    op.drop_index('ix_submissions_open_expires_at', table_name='submissions')
    op.drop_index(op.f('ix_failed_jobs_failed_at'), table_name='failed_jobs')
    op.drop_index(op.f('ix_failed_jobs_task_name'), table_name='failed_jobs')
    op.drop_index(op.f('ix_failed_jobs_task_id'), table_name='failed_jobs')
    op.drop_table('failed_jobs')
