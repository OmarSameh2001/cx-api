import uuid

from sqlalchemy.orm import Session

from common.dto import Page

from . import service
from .dto import NotificationRuleCreate, NotificationRuleRead, NotificationRuleSummary, NotificationRuleUpdate


def list_notification_rules(db: Session, *, tenant_id: uuid.UUID, limit: int, offset: int) -> Page[NotificationRuleSummary]:
    items, total = service.list_notification_rules(db, tenant_id=tenant_id, limit=limit, offset=offset)
    summaries = [NotificationRuleSummary.model_validate(r) for r in items]
    return Page(items=summaries, total=total, limit=limit, offset=offset)


def get_notification_rule(db: Session, rule_id: uuid.UUID) -> NotificationRuleRead:
    return NotificationRuleRead.model_validate(service.get_notification_rule(db, rule_id))


def create_notification_rule(db: Session, payload: NotificationRuleCreate) -> NotificationRuleRead:
    return NotificationRuleRead.model_validate(service.create_notification_rule(db, payload=payload))


def update_notification_rule(db: Session, rule_id: uuid.UUID, payload: NotificationRuleUpdate) -> NotificationRuleRead:
    return NotificationRuleRead.model_validate(service.update_notification_rule(db, rule_id, payload=payload))


def delete_notification_rule(db: Session, rule_id: uuid.UUID) -> None:
    service.delete_notification_rule(db, rule_id)
