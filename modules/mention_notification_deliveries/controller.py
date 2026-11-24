import uuid

from sqlalchemy.orm import Session

from common.dto import Page

from . import service
from .dto import MentionNotificationDeliveryCreate, MentionNotificationDeliveryRead, MentionNotificationDeliverySummary, MentionNotificationDeliveryUpdate


def list_mention_notification_deliveries(db: Session, *, tenant_id: uuid.UUID, organisation_id: int, limit: int, offset: int) -> Page[MentionNotificationDeliverySummary]:
    items, total = service.list_mention_notification_deliveries(db, tenant_id=tenant_id, organisation_id=organisation_id, limit=limit, offset=offset)
    summaries = [MentionNotificationDeliverySummary.model_validate(d) for d in items]
    return Page(items=summaries, total=total, limit=limit, offset=offset)


def get_notification_delivery(db: Session, delivery_id: uuid.UUID, organisation_id: int) -> MentionNotificationDeliveryRead:
    return MentionNotificationDeliveryRead.model_validate(service.get_notification_delivery(db, delivery_id, organisation_id))


def create_notification_delivery(db: Session, payload: MentionNotificationDeliveryCreate, organisation_id: int) -> MentionNotificationDeliveryRead:
    return MentionNotificationDeliveryRead.model_validate(service.create_notification_delivery(db, payload=payload, organisation_id=organisation_id))


def update_notification_delivery(db: Session, delivery_id: uuid.UUID, payload: MentionNotificationDeliveryUpdate, organisation_id: int) -> MentionNotificationDeliveryRead:
    return MentionNotificationDeliveryRead.model_validate(service.update_notification_delivery(db, delivery_id, organisation_id=organisation_id, payload=payload))


def delete_notification_delivery(db: Session, delivery_id: uuid.UUID, organisation_id: int) -> None:
    service.delete_notification_delivery(db, delivery_id, organisation_id)
