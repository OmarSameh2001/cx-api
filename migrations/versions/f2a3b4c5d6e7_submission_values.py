"""submission values

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-21 23:30:00.000000

E1.6: submission_values holds one row per answer of a finished submission,
for results queries; submissions.scores holds how each score was reached.
Both are empty after this migration: fill them from the stored answers with
`python scripts.py results:backfill`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('submissions', sa.Column('scores', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.create_table(
        'submission_values',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('submission_id', sa.Integer(), nullable=False),
        sa.Column('organisation_id', sa.Integer(), nullable=False),
        sa.Column('form_id', sa.Integer(), nullable=False),
        sa.Column('form_version_id', sa.Integer(), nullable=True),
        sa.Column('field_id', sa.Integer(), nullable=False),
        sa.Column('question_key', sa.String(length=32), nullable=False),
        sa.Column('question_type', sa.String(length=32), nullable=False),
        sa.Column('section_id', sa.Integer(), nullable=True),
        sa.Column('value_text', sa.Text(), nullable=True),
        sa.Column('value_number', sa.Float(), nullable=True),
        sa.Column('value_bool', sa.Boolean(), nullable=True),
        sa.Column('value_date', sa.Date(), nullable=True),
        sa.Column('value_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('max_score', sa.Float(), nullable=True),
        sa.Column('subject_employee_id', sa.Integer(), nullable=True),
        sa.Column('unit_id', sa.Integer(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['submission_id'], ['submissions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['form_id'], ['forms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['form_version_id'], ['form_versions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subject_employee_id'], ['employees.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('submission_id', 'field_id', name='uq_submission_values_submission_field'),
    )
    op.create_index(op.f('ix_submission_values_form_version_id'), 'submission_values', ['form_version_id'])
    op.create_index(
        'ix_submission_values_org_form_key_time', 'submission_values',
        ['organisation_id', 'form_id', 'question_key', 'submitted_at'],
    )
    op.create_index(
        'ix_submission_values_org_unit_time', 'submission_values',
        ['organisation_id', 'unit_id', 'submitted_at'],
    )
    op.create_index(
        'ix_submission_values_subject_time', 'submission_values',
        ['subject_employee_id', 'submitted_at'],
        postgresql_where=sa.text('subject_employee_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_submission_values_subject_time', table_name='submission_values')
    op.drop_index('ix_submission_values_org_unit_time', table_name='submission_values')
    op.drop_index('ix_submission_values_org_form_key_time', table_name='submission_values')
    op.drop_index(op.f('ix_submission_values_form_version_id'), table_name='submission_values')
    op.drop_table('submission_values')
    op.drop_column('submissions', 'scores')
