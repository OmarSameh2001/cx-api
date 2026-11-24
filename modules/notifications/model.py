from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base

DELIVERY_STATUSES = ("pending", "sending", "sent", "failed", "skipped")
DELIVERY_CHANNELS = ("email", "sms", "whatsapp", "slack")


class Notification(Base):
    """One in-app notification for one employee (E1.9): the bell.

    Only the template key and its parameters are stored; the words are
    rendered in the reader's language when read (see templates.py)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    recipient_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    # where clicking it goes, relative to the app (e.g. /form/12)
    link: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # the bell's list, newest first (ids grow with time; paged by id)
        Index("ix_notifications_recipient_id", "recipient_id", text("id DESC")),
        # the purge, by age
        Index("ix_notifications_time_brin", "created_at", postgresql_using="brin"),
        # the unread count, polled by every open app: only unread rows
        Index("ix_notifications_recipient_unread", "recipient_id", postgresql_where=text("read_at IS NULL")),
    )


class NotificationDelivery(Base):
    """One message to send on one channel (email, SMS, WhatsApp, Slack), and
    how sending it went. Rows are the worker's queue: pending rows that are
    due are sent, failures are retried with backoff."""

    __tablename__ = "notification_deliveries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    # the in-app notification it accompanies, if any
    notification_id: Mapped[Optional[int]] = mapped_column(ForeignKey("notifications.id", ondelete="SET NULL"))
    recipient_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    # email address, phone number, or Slack webhook/channel ("" = the provider's default)
    address: Mapped[str] = mapped_column(String(320), nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    link: Mapped[Optional[str]] = mapped_column(String(500))
    locale: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    provider: Mapped[Optional[str]] = mapped_column(String(32))
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(255))
    last_error: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'sending', 'sent', 'failed', 'skipped')",
                        name="ck_notification_deliveries_status"),
        # the worker's queue: only rows still to send
        Index("ix_notification_deliveries_due", "next_attempt_at",
              postgresql_where=text("status IN ('pending', 'sending')")),
        Index("ix_notification_deliveries_notification", "notification_id",
              postgresql_where=text("notification_id IS NOT NULL")),
        # the purge, by age
        Index("ix_notification_deliveries_time_brin", "created_at", postgresql_using="brin"),
    )
