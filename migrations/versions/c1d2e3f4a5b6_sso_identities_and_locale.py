"""sign-in identities, organisation sign-in settings, preferred language

Revision ID: c1d2e3f4a5b6
Revises: b9c0d1e2f3a4
Create Date: 2026-11-24 12:00:00.000000

E1.11: user_identities (the Google / Microsoft accounts an employee signs in
with, matched on the provider's stable id) and organisations.sign_in_settings.
E1.10: employees.preferred_locale. Adds only; nothing existing changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b9c0d1e2f3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_identities',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('organisation_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('tenant', sa.String(length=255), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'subject', name='uq_user_identities_provider_subject'),
        sa.UniqueConstraint('employee_id', 'provider', name='uq_user_identities_employee_provider'),
    )
    op.create_index('ix_user_identities_organisation', 'user_identities', ['organisation_id'])

    op.add_column(
        'organisations',
        sa.Column('sign_in_settings', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    )
    op.add_column('employees', sa.Column('preferred_locale', sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column('employees', 'preferred_locale')
    op.drop_column('organisations', 'sign_in_settings')
    op.drop_index('ix_user_identities_organisation', table_name='user_identities')
    op.drop_table('user_identities')
