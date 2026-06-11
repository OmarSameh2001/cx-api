"""add sections to forms

Revision ID: a1b2c3d4e5f6
Revises: fb270c24c299
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'fb270c24c299'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'forms',
        sa.Column('sections', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'form_fields',
        sa.Column('section_id', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('form_fields', 'section_id')
    op.drop_column('forms', 'sections')
