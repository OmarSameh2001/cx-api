import uuid

from sqlalchemy.orm import Session

from common.dto import Page

from . import service
from .dto import MentionNotificationRuleCreate, MentionNotificationRuleRead, MentionNotificationRuleSummary, MentionNotificationRuleUpdate


def list_mention_notification_rules(db: Session, *, tenant_id: uuid.UUID, organisation_id: int, limit: int, offset: int) -> Page[MentionNotificationRuleSummary]:
    items, total = service.list_mention_notification_rules(db, tenant_id=tenant_id, organisation_id=organisation_id, limit=limit, offset=offset)
    summaries = [MentionNotificationRuleSummary.model_validate(r) for r in items]
    return Page(items=summaries, total=total, limit=limit, offset=offset)


def get_notification_rule(db: Session, rule_id: uuid.UUID, organisation_id: int) -> MentionNotificationRuleRead:
    return MentionNotificationRuleRead.model_validate(service.get_notification_rule(db, rule_id, organisation_id))


def create_notification_rule(db: Session, payload: MentionNotificationRuleCreate, organisation_id: int) -> MentionNotificationRuleRead:
    return MentionNotificationRuleRead.model_validate(service.create_notification_rule(db, payload=payload, organisation_id=organisation_id))


def update_notification_rule(db: Session, rule_id: uuid.UUID, payload: MentionNotificationRuleUpdate, organisation_id: int) -> MentionNotificationRuleRead:
    return MentionNotificationRuleRead.model_validate(service.update_notification_rule(db, rule_id, organisation_id=organisation_id, payload=payload))


def delete_notification_rule(db: Session, rule_id: uuid.UUID, organisation_id: int) -> None:
    service.delete_notification_rule(db, rule_id, organisation_id)
