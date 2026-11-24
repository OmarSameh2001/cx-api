"""audit log, and the Mentions notification tables renamed

Revision ID: a8b9c0d1e2f3
Revises: f2a3b4c5d6e7
Create Date: 2026-11-23 12:00:00.000000

E1.8:
- audit_events, append-only: a trigger refuses UPDATE and TRUNCATE, and
  DELETE unless the retention purge has set cx.audit_purge for its
  transaction.
- audit:read joins the permission catalogue and is granted to every
  organisation's admin (system) role.

E1.9 groundwork (Mentions was dropped):
- notification_rules and notification_deliveries become
  mention_notification_rules and mention_notification_deliveries, so the new
  notification tables can use the plain names. Their data is kept.
- The permissions of the parked Mentions modules (mentions, keywords,
  notification_rules, notification_deliveries) leave the catalogue, with the
  roles' grants of them. Their routers are unmounted.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, Sequence[str], None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DROPPED_RESOURCES = ('mentions', 'keywords', 'notification_rules', 'notification_deliveries')
ACTIONS = ('read', 'create', 'update', 'delete')

APPEND_ONLY = """
CREATE OR REPLACE FUNCTION audit_events_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND current_setting('cx.audit_purge', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'audit_events is append-only (% refused)', TG_OP;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        'audit_events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('organisation_id', sa.Integer(), nullable=True),
        sa.Column('severity', sa.SmallInteger(), nullable=False),
        sa.Column('action', sa.String(length=48), nullable=False),
        sa.Column('entity_type', sa.String(length=24), nullable=True),
        sa.Column('entity_id', sa.BigInteger(), nullable=True),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('ip', postgresql.INET(), nullable=True),
        sa.Column('correlation_id', sa.UUID(), nullable=True),
        sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_events_org_time', 'audit_events',
                    ['organisation_id', sa.text('occurred_at DESC'), sa.text('id DESC')])
    op.create_index('ix_audit_events_org_entity', 'audit_events',
                    ['organisation_id', 'entity_type', 'entity_id', sa.text('occurred_at DESC')])
    op.create_index('ix_audit_events_org_actor', 'audit_events',
                    ['organisation_id', 'actor_id', sa.text('occurred_at DESC')],
                    postgresql_where=sa.text('actor_id IS NOT NULL'))
    op.create_index('ix_audit_events_time_brin', 'audit_events', ['occurred_at'], postgresql_using='brin')
    op.create_index('ix_audit_events_failed_login_ip', 'audit_events', ['ip', 'occurred_at'],
                    postgresql_where=sa.text("action = 'auth.login_failed'"))

    op.execute(APPEND_ONLY)
    op.execute(
        "CREATE TRIGGER audit_events_no_change BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only()"
    )

    bind = op.get_bind()
    # audit:read, for every organisation's admin role
    bind.execute(sa.text(
        "INSERT INTO permissions (resource, action) SELECT 'audit', 'read' "
        "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE resource = 'audit' AND action = 'read')"
    ))
    bind.execute(sa.text(
        "INSERT INTO role_permissions (role_id, permission_id, updated_at) "
        "SELECT r.id, p.id, now() FROM roles r "
        "JOIN permissions p ON p.resource = 'audit' AND p.action = 'read' "
        "WHERE r.is_system AND NOT EXISTS ("
        "  SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
    ))

    # the parked Mentions modules leave the permission catalogue
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE resource IN :res)"
        ).bindparams(sa.bindparam('res', expanding=True)),
        {'res': list(DROPPED_RESOURCES)},
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE resource IN :res").bindparams(
            sa.bindparam('res', expanding=True)
        ),
        {'res': list(DROPPED_RESOURCES)},
    )

    op.rename_table('notification_rules', 'mention_notification_rules')
    op.rename_table('notification_deliveries', 'mention_notification_deliveries')
    op.execute('ALTER INDEX ix_notification_rules_tenant_id RENAME TO ix_mention_notification_rules_tenant_id')
    op.execute('ALTER INDEX ix_notification_deliveries_tenant_id RENAME TO ix_mention_notification_deliveries_tenant_id')
    op.execute(
        'ALTER INDEX ix_notification_deliveries_notification_rule_id '
        'RENAME TO ix_mention_notification_deliveries_notification_rule_id'
    )


def downgrade() -> None:
    op.execute(
        'ALTER INDEX ix_mention_notification_deliveries_notification_rule_id '
        'RENAME TO ix_notification_deliveries_notification_rule_id'
    )
    op.execute('ALTER INDEX ix_mention_notification_deliveries_tenant_id RENAME TO ix_notification_deliveries_tenant_id')
    op.execute('ALTER INDEX ix_mention_notification_rules_tenant_id RENAME TO ix_notification_rules_tenant_id')
    op.rename_table('mention_notification_deliveries', 'notification_deliveries')
    op.rename_table('mention_notification_rules', 'notification_rules')

    bind = op.get_bind()
    # the Mentions permissions come back in the catalogue; which roles held
    # them is not restored
    for resource in DROPPED_RESOURCES:
        for action in ACTIONS:
            bind.execute(sa.text(
                "INSERT INTO permissions (resource, action) SELECT :r, :a "
                "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE resource = :r AND action = :a)"
            ), {'r': resource, 'a': action})
    bind.execute(sa.text(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE resource = 'audit')"
    ))
    bind.execute(sa.text("DELETE FROM permissions WHERE resource = 'audit'"))

    op.drop_table('audit_events')  # its triggers go with it
    op.execute('DROP FUNCTION IF EXISTS audit_events_append_only()')
