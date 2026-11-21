"""form versions

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-11-21 12:00:00.000000

E1.5: form_versions holds each published structure; forms.current_version_id
is what respondents get; form_fields.key is stable across versions;
submissions.form_version_id is the version answered. Every existing form gets
version 1 from its current structure, and its submissions point at it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'form_versions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('form_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('published_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['form_id'], ['forms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['published_by'], ['employees.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('form_id', 'number', name='uq_form_versions_form_number'),
    )
    op.create_index(op.f('ix_form_versions_form_id'), 'form_versions', ['form_id'], unique=False)

    op.add_column('form_fields', sa.Column('key', sa.String(length=32), nullable=True))
    op.execute("UPDATE form_fields SET key = replace(gen_random_uuid()::text, '-', '')")
    op.alter_column('form_fields', 'key', nullable=False)
    op.create_unique_constraint('uq_form_fields_form_key', 'form_fields', ['form_id', 'key'])

    op.add_column('forms', sa.Column('current_version_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_forms_current_version_id', 'forms', 'form_versions',
        ['current_version_id'], ['id'], ondelete='SET NULL',
    )

    op.add_column('submissions', sa.Column('form_version_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_submissions_form_version_id', 'submissions', 'form_versions', ['form_version_id'], ['id'],
    )
    op.create_index(op.f('ix_submissions_form_version_id'), 'submissions', ['form_version_id'], unique=False)

    # version 1 of every form: its structure now, in snapshot_of's shape
    op.execute(
        """
        INSERT INTO form_versions (form_id, number, snapshot, published_at, published_by)
        SELECT f.id, 1,
            jsonb_build_object(
                'type', f.type,
                'sections', f.sections,
                'fields', COALESCE((
                    SELECT jsonb_agg(jsonb_build_object(
                        'id', ff.id, 'key', ff.key, 'question', ff.question, 'type', ff.type,
                        'options', to_jsonb(ff.options), 'right_answer', ff.right_answer,
                        'order', ff."order", 'help_text', ff.help_text,
                        'is_required', ff.is_required, 'score_weight', ff.score_weight,
                        'section_id', ff.section_id, 'branching', ff.branching, 'config', ff.config
                    ) ORDER BY ff."order", ff.id)
                    FROM form_fields ff WHERE ff.form_id = f.id
                ), '[]'::jsonb)
            ),
            f.created_at, f.created_by
        FROM forms f
        """
    )
    op.execute(
        "UPDATE forms SET current_version_id = v.id FROM form_versions v WHERE v.form_id = forms.id"
    )
    op.execute(
        "UPDATE submissions SET form_version_id = f.current_version_id "
        "FROM forms f WHERE submissions.form_id = f.id"
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_submissions_form_version_id'), table_name='submissions')
    op.drop_constraint('fk_submissions_form_version_id', 'submissions', type_='foreignkey')
    op.drop_column('submissions', 'form_version_id')
    op.drop_constraint('fk_forms_current_version_id', 'forms', type_='foreignkey')
    op.drop_column('forms', 'current_version_id')
    op.drop_constraint('uq_form_fields_form_key', 'form_fields', type_='unique')
    op.drop_column('form_fields', 'key')
    op.drop_index(op.f('ix_form_versions_form_id'), table_name='form_versions')
    op.drop_table('form_versions')
