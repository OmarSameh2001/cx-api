import uuid
from datetime import datetime
from typing import Optional, Dict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .model import NotificationDelivery


def get_notification_delivery(db: Session, delivery_id: uuid.UUID) -> NotificationDelivery | None:
    return db.get(NotificationDelivery, delivery_id)


def list_notification_deliveries(db: Session, *, tenant_id: uuid.UUID, limit: int = 100, offset: int = 0) -> list[NotificationDelivery]:
    stmt = (
        select(NotificationDelivery)
        .where(NotificationDelivery.tenant_id == tenant_id)
        .order_by(NotificationDelivery.sent_at.desc().nullslast())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def count_notification_deliveries(db: Session, *, tenant_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count()).select_from(NotificationDelivery).where(NotificationDelivery.tenant_id == tenant_id)
    ).scalar_one()


def create_notification_delivery(
    db: Session,
    *,
    source_module: str,
    channel: str,
    recipient: str,
    status: str,
    notification_rule_id: uuid.UUID,
    tenant_id: uuid.UUID,
    context_type: Optional[str] = None,
    context_id: Optional[uuid.UUID] = None,
    payload: Optional[Dict] = None,
    sent_at: Optional[datetime] = None,
) -> NotificationDelivery:
    delivery = NotificationDelivery(
        source_module=source_module,
        channel=channel,
        recipient=recipient,
        status=status,
        notification_rule_id=notification_rule_id,
        tenant_id=tenant_id,
        context_type=context_type,
        context_id=context_id,
        payload=payload,
        sent_at=sent_at,
    )
    db.add(delivery)
    db.flush()
    return delivery


def update_notification_delivery(db: Session, delivery: NotificationDelivery, *, data: dict) -> NotificationDelivery:
    for key, value in data.items():
        setattr(delivery, key, value)
    db.flush()
    return delivery


def delete_notification_delivery(db: Session, delivery: NotificationDelivery) -> None:
    db.delete(delivery)
