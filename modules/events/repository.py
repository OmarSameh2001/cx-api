from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .model import OutboxEvent, ProcessedEvent


def add_event(db: Session, event: OutboxEvent) -> OutboxEvent:
    """Adds to the caller's transaction; the caller commits."""
    db.add(event)
    return event


def pending_event_ids(db: Session, *, now: datetime, limit: int) -> list[int]:
    stmt = (
        select(OutboxEvent.id)
        .where(OutboxEvent.status == "pending", OutboxEvent.available_at <= now)
        .order_by(OutboxEvent.available_at, OutboxEvent.id)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def lock_pending_event(db: Session, event_id: int) -> Optional[OutboxEvent]:
    """The event, locked for this transaction, unless another relay already
    holds it or it's no longer pending."""
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.id == event_id, OutboxEvent.status == "pending")
        .with_for_update(skip_locked=True)
    )
    return db.execute(stmt).scalar_one_or_none()


def processed_handlers(db: Session, event_id: int) -> set[str]:
    stmt = select(ProcessedEvent.handler).where(ProcessedEvent.event_id == event_id)
    return set(db.execute(stmt).scalars().all())


def mark_processed(db: Session, event_id: int, handler: str) -> None:
    db.add(ProcessedEvent(event_id=event_id, handler=handler))
    db.flush()


def delete_finished_before(db: Session, cutoff: datetime) -> int:
    """Deletes handled events (their processed_events rows go with them)."""
    result = db.execute(
        delete(OutboxEvent).where(
            OutboxEvent.status.in_(("done", "failed")),
            OutboxEvent.processed_at < cutoff,
        )
    )
    db.commit()
    return result.rowcount or 0
