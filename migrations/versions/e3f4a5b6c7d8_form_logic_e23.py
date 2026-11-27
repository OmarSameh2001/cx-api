"""form logic (E2.3): show or hide a question with a rule

Revision ID: e3f4a5b6c7d8
Revises: d1e2f3a4b5c6
Create Date: 2026-11-27 00:00:00.000000

form_fields.visible_if holds the rule (common/services/rules) that decides
whether a question is shown; null means always. Section routing lives in
forms.sections[].routes (JSONB already), so it needs no column. Existing
form_fields.branching is converted to routes when read (modules/forms/logic.py)
and on the next save, so no data is rewritten here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('form_fields', sa.Column('visible_if', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('form_fields', 'visible_if')
