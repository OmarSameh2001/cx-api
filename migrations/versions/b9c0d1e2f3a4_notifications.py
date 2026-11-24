"""notifications

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-11-23 13:00:00.000000

E1.9: notifications (in-app, one row per person) and
notification_deliveries (one message on one channel, and how sending it
went; the worker's queue). Both are scoped to an organisation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, Sequence[str], None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notifications',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('organisation_id', sa.Integer(), nullable=False),
        sa.Column('recipient_id', sa.Integer(), nullable=False),
        sa.Column('template', sa.String(length=64), nullable=False),
        sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('link', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recipient_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_notifications_recipient_id', 'notifications', ['recipient_id', sa.text('id DESC')])
    op.create_index('ix_notifications_recipient_unread', 'notifications', ['recipient_id'],
                    postgresql_where=sa.text('read_at IS NULL'))
    op.create_index('ix_notifications_time_brin', 'notifications', ['created_at'], postgresql_using='brin')

    op.create_table(
        'notification_deliveries',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('organisation_id', sa.Integer(), nullable=False),
        sa.Column('notification_id', sa.BigInteger(), nullable=True),
        sa.Column('recipient_id', sa.Integer(), nullable=True),
        sa.Column('channel', sa.String(length=16), nullable=False),
        sa.Column('address', sa.String(length=320), nullable=False),
        sa.Column('template', sa.String(length=64), nullable=False),
        sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('link', sa.String(length=500), nullable=True),
        sa.Column('locale', sa.String(length=8), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
        sa.Column('attempts', sa.SmallInteger(), server_default='0', nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=True),
        sa.Column('provider_message_id', sa.String(length=255), nullable=True),
        sa.Column('last_error', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['notification_id'], ['notifications.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['recipient_id'], ['employees.id'], ondelete='SET NULL'),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed', 'skipped')", name='ck_notification_deliveries_status'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_notification_deliveries_due', 'notification_deliveries', ['next_attempt_at'],
                    postgresql_where=sa.text("status IN ('pending', 'sending')"))
    op.create_index('ix_notification_deliveries_notification', 'notification_deliveries', ['notification_id'],
                    postgresql_where=sa.text('notification_id IS NOT NULL'))
    op.create_index('ix_notification_deliveries_time_brin', 'notification_deliveries', ['created_at'],
                    postgresql_using='brin')


def downgrade() -> None:
    op.drop_table('notification_deliveries')
    op.drop_table('notifications')
