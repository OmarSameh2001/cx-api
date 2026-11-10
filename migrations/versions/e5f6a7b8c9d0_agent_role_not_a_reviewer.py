"""agent role is not a reviewer

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-11 00:00:00.000000

submissions:read means reviewing every submission of the organisation (and
seeing correct exam answers). The default "agent" role had it, plus the
unused submissions:create. Take both off every non-system role still named
"agent", matching the new DEFAULT_ROLES.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AGENT_ROLES = "SELECT id FROM roles WHERE name = 'agent' AND is_system = false"
PERMS = (
    "SELECT id FROM permissions WHERE resource = 'submissions' "
    "AND action IN ('read', 'create')"
)


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        f"DELETE FROM role_permissions WHERE role_id IN ({AGENT_ROLES}) "
        f"AND permission_id IN ({PERMS})"
    ))


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "INSERT INTO role_permissions (role_id, permission_id) "
        f"SELECT r.id, p.id FROM ({AGENT_ROLES}) r CROSS JOIN ({PERMS}) p "
        "WHERE NOT EXISTS (SELECT 1 FROM role_permissions rp "
        "WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
    ))
