import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.notification_rules import repository as notification_rules_repository
from modules.tenants.service import ensure_tenant_in_organisation, tenant_in_organisation

from . import repository
from .dto import NotificationDeliveryCreate, NotificationDeliveryUpdate
from .model import NotificationDelivery


def _ensure_notification_delivery(db: Session, delivery_id: uuid.UUID, organisation_id: int) -> NotificationDelivery:
    delivery = repository.get_notification_delivery(db, delivery_id)
    # another organisation's row is reported as missing
    if delivery is None or not tenant_in_organisation(db, delivery.tenant_id, organisation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification delivery not found")
    return delivery


def list_notification_deliveries(db: Session, *, tenant_id: uuid.UUID, organisation_id: int, limit: int, offset: int) -> tuple[list[NotificationDelivery], int]:
    ensure_tenant_in_organisation(db, tenant_id, organisation_id)
    items = repository.list_notification_deliveries(db, tenant_id=tenant_id, limit=limit, offset=offset)
    total = repository.count_notification_deliveries(db, tenant_id=tenant_id)
    return items, total


def get_notification_delivery(db: Session, delivery_id: uuid.UUID, organisation_id: int) -> NotificationDelivery:
    return _ensure_notification_delivery(db, delivery_id, organisation_id)


def create_notification_delivery(db: Session, *, payload: NotificationDeliveryCreate, organisation_id: int) -> NotificationDelivery:
    ensure_tenant_in_organisation(db, payload.tenant_id, organisation_id)
    # the rule must be one of this tenant's, not another tenant's
    rule = notification_rules_repository.get_notification_rule(db, payload.notification_rule_id)
    if rule is None or rule.tenant_id != payload.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification rule not found")
    delivery = repository.create_notification_delivery(
        db,
        source_module=payload.source_module,
        channel=payload.channel,
        recipient=payload.recipient,
        status=payload.status,
        notification_rule_id=payload.notification_rule_id,
        tenant_id=payload.tenant_id,
        context_type=payload.context_type,
        context_id=payload.context_id,
        payload=payload.payload,
        sent_at=payload.sent_at,
    )
    db.commit()
    return repository.get_notification_delivery(db, delivery.id)


def update_notification_delivery(db: Session, delivery_id: uuid.UUID, *, organisation_id: int, payload: NotificationDeliveryUpdate) -> NotificationDelivery:
    delivery = _ensure_notification_delivery(db, delivery_id, organisation_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return delivery
    repository.update_notification_delivery(db, delivery, data=data)
    db.commit()
    return repository.get_notification_delivery(db, delivery_id)


def delete_notification_delivery(db: Session, delivery_id: uuid.UUID, organisation_id: int) -> None:
    delivery = _ensure_notification_delivery(db, delivery_id, organisation_id)
    repository.delete_notification_delivery(db, delivery)
    db.commit()
