import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, Index, Integer, SmallInteger, String, func, text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class AuditEvent(Base):
    """One thing that happened (E1.8), append-only: a database trigger
    refuses UPDATE, and DELETE except from the retention purge.

    The columns are the ones every query filters or sorts by. Everything
    that varies by kind of event is in two small JSONB documents:

    changes  the change log, Odoo-style, for records with tracked fields:
             {"field": [old, new]} per changed field, nested settings as
             dotted keys ({"settings.max_attempts": [1, 3]}), lists as
             {"field": {"added": [...], "removed": [...]}}, and personal
             data as {"field": {"hidden": true}}. Only what changed is
             stored, and long values are cut short.
    data     a few details of the event (a version number, a count).

    No personal data: the actor is an employee id, never a name or email.
    Organisation and actor ids have no foreign keys, so the history outlives
    the records it describes.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # null for platform-level events and sign-ins to unknown accounts
    organisation_id: Mapped[Optional[int]] = mapped_column(Integer)
    severity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(24))
    entity_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    # the employee who did it; null for the system (jobs) and signed-out callers
    actor_id: Mapped[Optional[int]] = mapped_column(Integer)
    ip: Mapped[Optional[str]] = mapped_column(INET)
    # every entry written by one request shares it (X-Request-ID)
    correlation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    changes: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)

    __table_args__ = (
        # the audit screen: newest first within an organisation
        Index("ix_audit_events_org_time", "organisation_id", text("occurred_at DESC"), text("id DESC")),
        # one record's change log
        Index("ix_audit_events_org_entity", "organisation_id", "entity_type", "entity_id",
              text("occurred_at DESC")),
        # what one person did
        Index("ix_audit_events_org_actor", "organisation_id", "actor_id", text("occurred_at DESC"),
              postgresql_where=text("actor_id IS NOT NULL")),
        # the retention purge (by age); BRIN is a few pages for millions of rows
        Index("ix_audit_events_time_brin", "occurred_at", postgresql_using="brin"),
        # counting recent failed sign-ins from one IP
        Index("ix_audit_events_failed_login_ip", "ip", "occurred_at",
              postgresql_where=text("action = 'auth.login_failed'")),
    )
