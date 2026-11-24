from datetime import datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from modules.employees.model import Employee

from .model import Notification, NotificationDelivery


def add(db: Session, rows: Sequence[object]) -> None:
    for row in rows:
        db.add(row)


def recipients(db: Session, *, organisation_id: int, employee_ids: Sequence[int]) -> list[Employee]:
    """The organisation's active employees among `employee_ids`."""
    if not employee_ids:
        return []
    stmt = select(Employee).where(
        Employee.id.in_(list(employee_ids)),
        Employee.organisation_id == organisation_id,
        Employee.is_active.is_(True),
    )
    return list(db.execute(stmt).scalars().all())


# --- in-app -----------------------------------------------------------------------


def list_for(
    db: Session, *, recipient_id: int, before_id: Optional[int], limit: int, unread_only: bool
) -> list[Notification]:
    stmt = select(Notification).where(Notification.recipient_id == recipient_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if before_id is not None:
        stmt = stmt.where(Notification.id < before_id)
    return list(db.execute(stmt.order_by(Notification.id.desc()).limit(limit)).scalars().all())


def unread_count(db: Session, *, recipient_id: int) -> int:
    stmt = select(func.count()).select_from(Notification).where(
        Notification.recipient_id == recipient_id, Notification.read_at.is_(None)
    )
    return int(db.execute(stmt).scalar_one())


def mark_read(db: Session, *, recipient_id: int, at: datetime, ids: Optional[Sequence[int]] = None) -> int:
    stmt = (
        update(Notification)
        .where(Notification.recipient_id == recipient_id, Notification.read_at.is_(None))
        .values(read_at=at)
        .execution_options(synchronize_session=False)
    )
    if ids is not None:
        stmt = stmt.where(Notification.id.in_(list(ids)))
    return db.execute(stmt).rowcount or 0


def mark_unread(db: Session, *, recipient_id: int, notification_id: int) -> int:
    stmt = (
        update(Notification)
        .where(Notification.recipient_id == recipient_id, Notification.id == notification_id)
        .values(read_at=None)
        .execution_options(synchronize_session=False)
    )
    return db.execute(stmt).rowcount or 0


# --- deliveries -------------------------------------------------------------------


def claim_due(db: Session, *, now: datetime, limit: int, hold: timedelta) -> list[NotificationDelivery]:
    """Takes up to `limit` deliveries that are due: pending ones, and ones
    left "sending" by a worker that died (their hold ran out). They become
    "sending" until `now + hold`; SKIP LOCKED keeps two workers apart."""
    stmt = (
        select(NotificationDelivery)
        .where(
            NotificationDelivery.status.in_(("pending", "sending")),
            NotificationDelivery.next_attempt_at <= now,
        )
        .order_by(NotificationDelivery.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list(db.execute(stmt).scalars().all())
    for row in rows:
        row.status = "sending"
        row.attempts = (row.attempts or 0) + 1
        row.next_attempt_at = now + hold
    return rows


def deliveries_for(db: Session, notification_ids: Sequence[int]) -> list[NotificationDelivery]:
    if not notification_ids:
        return []
    stmt = select(NotificationDelivery).where(NotificationDelivery.notification_id.in_(list(notification_ids)))
    return list(db.execute(stmt).scalars().all())


# --- retention ---------------------------------------------------------------------


def purge(db: Session, *, read_before: datetime, unread_before: datetime, deliveries_before: datetime) -> dict[str, int]:
    deliveries = db.execute(
        delete(NotificationDelivery)
        .where(
            NotificationDelivery.created_at < deliveries_before,
            NotificationDelivery.status.in_(("sent", "failed", "skipped")),
        )
        .execution_options(synchronize_session=False)
    ).rowcount or 0
    notifications = db.execute(
        delete(Notification)
        .where(or_(
            and_(Notification.read_at.is_not(None), Notification.created_at < read_before),
            Notification.created_at < unread_before,
        ))
        .execution_options(synchronize_session=False)
    ).rowcount or 0
    return {"notifications": notifications, "deliveries": deliveries}
