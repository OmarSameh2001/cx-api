"""form settings (E2.2): what a submission keeps for them

Revision ID: d1e2f3a4b5c6
Revises: c1d2e3f4a5b6
Create Date: 2026-11-27 00:00:00.000000

The settings themselves live in forms.settings (JSONB), so they need no
column. Submissions gain:
- respondent_key: a keyed hash standing in for who answered an anonymous
  form (T2.2.8), so one response per person still holds (T2.2.4);
- hidden_fields: values from a signed prefilled link (T2.2.7);
- question_order: the shuffled order this attempt was shown (T2.2.9);
- edited_at: the last time the respondent changed a submitted response (T2.2.11).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('submissions', sa.Column('respondent_key', sa.String(length=64), nullable=True))
    op.add_column('submissions', sa.Column('hidden_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('submissions', sa.Column('question_order', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('submissions', sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        'ix_submissions_form_respondent_key', 'submissions', ['form_id', 'respondent_key'],
        postgresql_where=sa.text('respondent_key IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_submissions_form_respondent_key', table_name='submissions')
    op.drop_column('submissions', 'edited_at')
    op.drop_column('submissions', 'question_order')
    op.drop_column('submissions', 'hidden_fields')
    op.drop_column('submissions', 'respondent_key')
