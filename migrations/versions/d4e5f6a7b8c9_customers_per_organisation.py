"""customers per organisation, contact on submissions, no customer login

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-11 00:00:00.000000

- customers.organisation_id. Email is unique per organisation (case-insensitive)
  and external_id unique per organisation, instead of both being global.
  Existing customers were global: each one is kept (same id) for the first
  organisation whose forms it answered (the oldest organisation if none) and
  copied into every other organisation it answered, with those submissions
  pointed at the copy.
- submissions.contact: the contact details given with a public submission.
  Backfilled from the customer record for existing customer submissions.
- Customer login is gone: drop customers.is_auth, password, email_code and
  refresh_tokens.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# everything a copy carries over (id and organisation_id are set per copy)
COPY_COLUMNS = 'external_id, first_name, last_name, email, phone, "DOB", gender, profile_picture'


def _merge_duplicates(bind, group_by: str) -> None:
    """Keep the lowest id per group, point submissions at it, drop the rest."""
    dupes = f"(SELECT id, MIN(id) OVER (PARTITION BY {group_by}) AS keep_id FROM customers)"
    bind.execute(sa.text(
        f"UPDATE submissions s SET customer_id = d.keep_id FROM {dupes} d "
        "WHERE s.customer_id = d.id AND d.id <> d.keep_id"
    ))
    bind.execute(sa.text(
        f"DELETE FROM customers c USING {dupes} d WHERE c.id = d.id AND d.id <> d.keep_id"
    ))


def upgrade() -> None:
    op.add_column('customers', sa.Column('organisation_id', sa.Integer(), nullable=True))
    op.add_column('submissions', sa.Column('contact', sa.JSON(), nullable=True))
    # global uniqueness goes before the per-organisation copies are made
    op.drop_index('ix_customers_email', table_name='customers')
    op.drop_index('ix_customers_external_id', table_name='customers')
    # login columns go first too: copies would need values for them
    op.drop_column('customers', 'is_auth')
    op.drop_column('customers', 'password')
    op.drop_column('customers', 'email_code')
    op.drop_column('customers', 'refresh_tokens')

    bind = op.get_bind()
    org_ids = [r[0] for r in bind.execute(sa.text("SELECT id FROM organisations ORDER BY id"))]
    customers = [r[0] for r in bind.execute(sa.text("SELECT id FROM customers ORDER BY id"))]

    for customer_id in customers:
        answered = [r[0] for r in bind.execute(
            sa.text(
                "SELECT DISTINCT f.organisation_id FROM submissions s "
                "JOIN forms f ON f.id = s.form_id WHERE s.customer_id = :c "
                "ORDER BY f.organisation_id"
            ),
            {'c': customer_id},
        )]
        targets = answered or org_ids[:1]
        if not targets:
            # no organisation at all, so nothing it could belong to
            bind.execute(sa.text("DELETE FROM customers WHERE id = :c"), {'c': customer_id})
            continue
        bind.execute(
            sa.text("UPDATE customers SET organisation_id = :o WHERE id = :c"),
            {'o': targets[0], 'c': customer_id},
        )
        for org_id in targets[1:]:
            new_id = bind.execute(
                sa.text(
                    f"INSERT INTO customers (organisation_id, {COPY_COLUMNS}) "
                    f"SELECT :o, {COPY_COLUMNS} FROM customers WHERE id = :c RETURNING id"
                ),
                {'o': org_id, 'c': customer_id},
            ).scalar_one()
            bind.execute(
                sa.text(
                    "UPDATE submissions s SET customer_id = :new FROM forms f "
                    "WHERE f.id = s.form_id AND s.customer_id = :old AND f.organisation_id = :o"
                ),
                {'new': new_id, 'old': customer_id, 'o': org_id},
            )

    # emails are stored lowercased from now on; fold case duplicates together
    bind.execute(sa.text("UPDATE customers SET email = lower(trim(email))"))
    _merge_duplicates(bind, "organisation_id, email")

    bind.execute(sa.text(
        "UPDATE submissions s SET contact = json_build_object("
        "'email', c.email, 'first_name', c.first_name, "
        "'last_name', c.last_name, 'phone', c.phone) "
        "FROM customers c WHERE c.id = s.customer_id AND s.contact IS NULL"
    ))

    op.alter_column('customers', 'organisation_id', nullable=False)
    op.create_foreign_key(
        'customers_organisation_id_fkey', 'customers', 'organisations',
        ['organisation_id'], ['id'], ondelete='CASCADE',
    )
    op.create_index(op.f('ix_customers_organisation_id'), 'customers', ['organisation_id'])
    op.create_index(op.f('ix_customers_email'), 'customers', ['email'])
    op.create_index(
        'uq_customers_organisation_id_email', 'customers',
        ['organisation_id', sa.text('lower(email)')], unique=True,
    )
    op.create_unique_constraint(
        'uq_customers_organisation_id_external_id', 'customers',
        ['organisation_id', 'external_id'],
    )



def downgrade() -> None:
    # Customer login columns come back empty (nobody can log in until set).
    # Per-organisation copies of one email collapse back into a single global
    # customer; submissions.contact is dropped.
    op.add_column('customers', sa.Column(
        'refresh_tokens', postgresql.ARRAY(sa.String(length=64)),
        server_default='{}', nullable=False,
    ))
    op.add_column('customers', sa.Column('email_code', sa.String(length=16), nullable=True))
    op.add_column('customers', sa.Column('password', sa.String(length=255), nullable=True))
    op.add_column('customers', sa.Column(
        'is_auth', sa.Boolean(), server_default='false', nullable=False,
    ))

    op.drop_constraint('uq_customers_organisation_id_external_id', 'customers', type_='unique')
    op.drop_index('uq_customers_organisation_id_email', table_name='customers')
    op.drop_index(op.f('ix_customers_email'), table_name='customers')
    op.drop_index(op.f('ix_customers_organisation_id'), table_name='customers')
    op.drop_constraint('customers_organisation_id_fkey', 'customers', type_='foreignkey')

    bind = op.get_bind()
    _merge_duplicates(bind, "lower(email)")
    # copies shared their external_id; after the email merge, clear any that
    # still clash so the global unique index can return
    bind.execute(sa.text(
        "UPDATE customers c SET external_id = NULL FROM "
        "(SELECT id, MIN(id) OVER (PARTITION BY external_id) AS keep_id FROM customers "
        "WHERE external_id IS NOT NULL) d WHERE c.id = d.id AND d.id <> d.keep_id"
    ))

    op.drop_column('customers', 'organisation_id')
    op.create_index('ix_customers_email', 'customers', ['email'], unique=True)
    op.create_index('ix_customers_external_id', 'customers', ['external_id'], unique=True)
    op.drop_column('submissions', 'contact')
