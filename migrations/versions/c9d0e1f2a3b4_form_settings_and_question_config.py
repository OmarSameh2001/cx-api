"""form settings and question config

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-21 00:00:00.000000

forms.settings (T1.4.2) takes over time_limit_minutes, max_attempts and
results_revealed. form_fields.config (T1.4.1) holds per-type question
settings; file questions' "key=value" limits stay in options, which is still
read under the config.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('form_fields', sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column(
        'forms',
        sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.execute(
        """
        UPDATE forms SET settings = jsonb_build_object(
            'time_limit_minutes', time_limit_minutes,
            'max_attempts', max_attempts,
            'results_revealed', results_revealed
        )
        """
    )
    op.drop_column('forms', 'results_revealed')
    op.drop_column('forms', 'max_attempts')
    op.drop_column('forms', 'time_limit_minutes')


def downgrade() -> None:
    op.add_column('forms', sa.Column('time_limit_minutes', sa.Integer(), nullable=True))
    op.add_column('forms', sa.Column('max_attempts', sa.Integer(), nullable=True))
    op.add_column(
        'forms',
        sa.Column('results_revealed', sa.Boolean(), server_default='false', nullable=False),
    )
    op.execute(
        """
        UPDATE forms SET
            time_limit_minutes = (settings->>'time_limit_minutes')::int,
            max_attempts = (settings->>'max_attempts')::int,
            results_revealed = COALESCE((settings->>'results_revealed')::boolean, false)
        """
    )
    op.drop_column('forms', 'settings')
    op.drop_column('form_fields', 'config')
