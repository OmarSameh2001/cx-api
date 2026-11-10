"""roles per organisation and platform admin flag

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-10 00:00:00.000000

- employees.is_platform_admin (default false)
- roles.organisation_id, unique (organisation_id, name) instead of unique name.
  Existing roles were global: each one is kept (same id) for the oldest
  organisation and copied, with its permissions, into every other one.
  Employees are pointed at their own organisation's copy.
- organisations:* and tenants:* stop being role permissions.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PLATFORM_RESOURCES = ('organisations', 'tenants')


def upgrade() -> None:
    op.add_column(
        'employees',
        sa.Column('is_platform_admin', sa.Boolean(), server_default='false', nullable=False),
    )
    op.add_column('roles', sa.Column('organisation_id', sa.Integer(), nullable=True))
    # Before copying: the copies reuse the names.
    op.drop_constraint('roles_name_key', 'roles', type_='unique')

    bind = op.get_bind()

    # Platform permissions leave the role catalogue.
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE resource IN :res)"
        ).bindparams(sa.bindparam('res', expanding=True)),
        {'res': list(PLATFORM_RESOURCES)},
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE resource IN :res").bindparams(
            sa.bindparam('res', expanding=True)
        ),
        {'res': list(PLATFORM_RESOURCES)},
    )

    org_ids = [r[0] for r in bind.execute(sa.text("SELECT id FROM organisations ORDER BY id"))]
    roles = bind.execute(sa.text("SELECT id, name, is_system FROM roles ORDER BY id")).all()

    if not org_ids:
        # Roles can't belong to anyone; no employee can exist without an org.
        bind.execute(sa.text("DELETE FROM role_permissions"))
        bind.execute(sa.text("DELETE FROM roles"))
    else:
        first_org, other_orgs = org_ids[0], org_ids[1:]
        for role_id, name, is_system in roles:
            bind.execute(
                sa.text("UPDATE roles SET organisation_id = :org WHERE id = :id"),
                {'org': first_org, 'id': role_id},
            )
            for org_id in other_orgs:
                new_id = bind.execute(
                    sa.text(
                        "INSERT INTO roles (name, is_system, organisation_id) "
                        "VALUES (:name, :sys, :org) RETURNING id"
                    ),
                    {'name': name, 'sys': is_system, 'org': org_id},
                ).scalar_one()
                bind.execute(
                    sa.text(
                        "INSERT INTO role_permissions (role_id, permission_id, updated_by, updated_at) "
                        "SELECT :new, permission_id, updated_by, updated_at "
                        "FROM role_permissions WHERE role_id = :old"
                    ),
                    {'new': new_id, 'old': role_id},
                )
                bind.execute(
                    sa.text(
                        "UPDATE employees SET role_id = :new "
                        "WHERE role_id = :old AND organisation_id = :org"
                    ),
                    {'new': new_id, 'old': role_id, 'org': org_id},
                )

    op.alter_column('roles', 'organisation_id', nullable=False)
    op.create_foreign_key(
        'roles_organisation_id_fkey', 'roles', 'organisations',
        ['organisation_id'], ['id'], ondelete='CASCADE',
    )
    op.create_index(op.f('ix_roles_organisation_id'), 'roles', ['organisation_id'], unique=False)
    op.create_unique_constraint(
        'uq_roles_organisation_id_name', 'roles', ['organisation_id', 'name']
    )


def downgrade() -> None:
    # Collapse each role name back to one global role: keep the lowest id,
    # point every employee at it, drop the copies. Per-organisation edits to
    # the copies are lost. organisations:* / tenants:* permissions are not
    # restored; `POST /roles/permissions/seed` on the old code recreates them.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE employees e SET role_id = k.keep_id "
            "FROM roles r JOIN (SELECT name, MIN(id) AS keep_id FROM roles GROUP BY name) k "
            "ON k.name = r.name "
            "WHERE e.role_id = r.id AND r.id <> k.keep_id"
        )
    )
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE role_id IN ("
            "SELECT r.id FROM roles r JOIN (SELECT name, MIN(id) AS keep_id FROM roles GROUP BY name) k "
            "ON k.name = r.name WHERE r.id <> k.keep_id)"
        )
    )
    bind.execute(
        sa.text(
            "DELETE FROM roles r USING (SELECT name, MIN(id) AS keep_id FROM roles GROUP BY name) k "
            "WHERE k.name = r.name AND r.id <> k.keep_id"
        )
    )

    op.drop_constraint('uq_roles_organisation_id_name', 'roles', type_='unique')
    op.create_unique_constraint('roles_name_key', 'roles', ['name'])
    op.drop_index(op.f('ix_roles_organisation_id'), table_name='roles')
    op.drop_constraint('roles_organisation_id_fkey', 'roles', type_='foreignkey')
    op.drop_column('roles', 'organisation_id')
    op.drop_column('employees', 'is_platform_admin')
