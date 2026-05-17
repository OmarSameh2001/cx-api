import uuid

from sqlalchemy.orm import Session

from common.dto import Page

from . import service
from .dto import NotificationDeliveryCreate, NotificationDeliveryRead, NotificationDeliverySummary, NotificationDeliveryUpdate


def list_notification_deliveries(db: Session, *, tenant_id: uuid.UUID, limit: int, offset: int) -> Page[NotificationDeliverySummary]:
    items, total = service.list_notification_deliveries(db, tenant_id=tenant_id, limit=limit, offset=offset)
    summaries = [NotificationDeliverySummary.model_validate(d) for d in items]
    return Page(items=summaries, total=total, limit=limit, offset=offset)


def get_notification_delivery(db: Session, delivery_id: uuid.UUID) -> NotificationDeliveryRead:
    return NotificationDeliveryRead.model_validate(service.get_notification_delivery(db, delivery_id))


def create_notification_delivery(db: Session, payload: NotificationDeliveryCreate) -> NotificationDeliveryRead:
    return NotificationDeliveryRead.model_validate(service.create_notification_delivery(db, payload=payload))


def update_notification_delivery(db: Session, delivery_id: uuid.UUID, payload: NotificationDeliveryUpdate) -> NotificationDeliveryRead:
    return NotificationDeliveryRead.model_validate(service.update_notification_delivery(db, delivery_id, payload=payload))


def delete_notification_delivery(db: Session, delivery_id: uuid.UUID) -> None:
    service.delete_notification_delivery(db, delivery_id)
