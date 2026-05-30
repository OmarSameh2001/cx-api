import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .model import NotificationRule


def get_notification_rule(db: Session, rule_id: uuid.UUID) -> NotificationRule | None:
    return db.get(NotificationRule, rule_id)


def list_notification_rules(db: Session, *, tenant_id: uuid.UUID, limit: int = 100, offset: int = 0) -> list[NotificationRule]:
    stmt = (
        select(NotificationRule)
        .where(NotificationRule.tenant_id == tenant_id)
        .order_by(NotificationRule.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def count_notification_rules(db: Session, *, tenant_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count()).select_from(NotificationRule).where(NotificationRule.tenant_id == tenant_id)
    ).scalar_one()


def create_notification_rule(
    db: Session,
    *,
    source_module: str,
    rule_type: str,
    tenant_id: uuid.UUID,
    platform: Optional[str] = None,
    threshold_value: Optional[float] = None,
    time_window_min: Optional[int] = None,
    email_enabled: bool = False,
    in_app_enabled: bool = False,
    is_active: bool = True,
) -> NotificationRule:
    rule = NotificationRule(
        source_module=source_module,
        rule_type=rule_type,
        tenant_id=tenant_id,
        platform=platform,
        threshold_value=threshold_value,
        time_window_min=time_window_min,
        email_enabled=email_enabled,
        in_app_enabled=in_app_enabled,
        is_active=is_active,
    )
    db.add(rule)
    db.flush()
    return rule


def update_notification_rule(db: Session, rule: NotificationRule, *, data: dict) -> NotificationRule:
    for key, value in data.items():
        setattr(rule, key, value)
    db.flush()
    return rule


def delete_notification_rule(db: Session, rule: NotificationRule) -> None:
    db.delete(rule)
