from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base

EVENT_TYPES = (
    "submission.submitted",
    "submission.late",
    "submission.graded",
    "submission.expired",
    "form.published",
    "file.uploaded",
)

# pending: waiting for its handlers; done: every handler ran;
# failed: a handler ran out of attempts (logged to failed_jobs)
EventStatus = ("pending", "done", "failed")


class OutboxEvent(Base):
    """Something that happened, written in the same transaction as the data
    it describes, so an event exists exactly when its change was saved."""

    __tablename__ = "event_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    organisation_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # not picked up before this (pushed back after a failed attempt)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # the relay's queue: pending events in order
        Index(
            "ix_event_outbox_pending",
            "available_at",
            "id",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_event_outbox_aggregate", "aggregate_type", "aggregate_id"),
        # the retention purge: handled events by age
        Index(
            "ix_event_outbox_finished",
            "processed_at",
            postgresql_where=text("status IN ('done', 'failed')"),
        ),
    )


class ProcessedEvent(Base):
    """One row per (event, handler) that finished. Written in the same
    transaction as the handler's own changes, so a handler never runs twice
    for one event, even after a crash or a retried relay."""

    __tablename__ = "processed_events"

    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("event_outbox.id", ondelete="CASCADE"), primary_key=True
    )
    handler: Mapped[str] = mapped_column(String(200), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
