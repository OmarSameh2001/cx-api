"""feed and outbox purge indexes

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-11-21 23:00:00.000000

- mentions (tenant_id, published_at): the tenant feed sorts by published_at
  desc; only tenant_id was indexed, so every page sorted the whole feed.
- event_outbox processed_at, partial on handled events: the daily retention
  purge deletes by status and age, which scanned the whole outbox.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_mentions_tenant_published', 'mentions', ['tenant_id', 'published_at'])
    op.create_index(
        'ix_event_outbox_finished', 'event_outbox', ['processed_at'],
        postgresql_where=sa.text("status IN ('done', 'failed')"),
    )


def downgrade() -> None:
    op.drop_index('ix_event_outbox_finished', table_name='event_outbox')
    op.drop_index('ix_mentions_tenant_published', table_name='mentions')
