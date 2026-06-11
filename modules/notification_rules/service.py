import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import repository
from .dto import NotificationRuleCreate, NotificationRuleUpdate
from .model import NotificationRule


def _ensure_notification_rule(db: Session, rule_id: uuid.UUID) -> NotificationRule:
    rule = repository.get_notification_rule(db, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification rule not found")
    return rule


def list_notification_rules(db: Session, *, tenant_id: uuid.UUID, limit: int, offset: int) -> tuple[list[NotificationRule], int]:
    items = repository.list_notification_rules(db, tenant_id=tenant_id, limit=limit, offset=offset)
    total = repository.count_notification_rules(db, tenant_id=tenant_id)
    return items, total


def get_notification_rule(db: Session, rule_id: uuid.UUID) -> NotificationRule:
    return _ensure_notification_rule(db, rule_id)


def create_notification_rule(db: Session, *, payload: NotificationRuleCreate) -> NotificationRule:
    rule = repository.create_notification_rule(
        db,
        source_module=payload.source_module,
        rule_type=payload.rule_type,
        tenant_id=payload.tenant_id,
        platform=payload.platform,
        threshold_value=payload.threshold_value,
        time_window_min=payload.time_window_min,
        email_enabled=payload.email_enabled,
        in_app_enabled=payload.in_app_enabled,
        is_active=payload.is_active,
    )
    db.commit()
    return repository.get_notification_rule(db, rule.id)


def update_notification_rule(db: Session, rule_id: uuid.UUID, *, payload: NotificationRuleUpdate) -> NotificationRule:
    rule = _ensure_notification_rule(db, rule_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return rule
    repository.update_notification_rule(db, rule, data=data)
    db.commit()
    return repository.get_notification_rule(db, rule_id)


def delete_notification_rule(db: Session, rule_id: uuid.UUID) -> None:
    rule = _ensure_notification_rule(db, rule_id)
    repository.delete_notification_rule(db, rule)
    db.commit()
