import uuid

from sqlalchemy.orm import Session

from common.dto import Page

from . import service
from .dto import MentionCreate, MentionRead, MentionSummary, MentionUpdate


def list_mentions(db: Session, *, tenant_id: uuid.UUID, limit: int, offset: int) -> Page[MentionSummary]:
    items, total = service.list_mentions(db, tenant_id=tenant_id, limit=limit, offset=offset)
    summaries = [MentionSummary.model_validate(m) for m in items]
    return Page(items=summaries, total=total, limit=limit, offset=offset)


def get_mention(db: Session, mention_id: uuid.UUID) -> MentionRead:
    return MentionRead.model_validate(service.get_mention(db, mention_id))


def create_mention(db: Session, payload: MentionCreate) -> MentionRead:
    return MentionRead.model_validate(service.create_mention(db, payload=payload))


def update_mention(db: Session, mention_id: uuid.UUID, payload: MentionUpdate) -> MentionRead:
    return MentionRead.model_validate(service.update_mention(db, mention_id, payload=payload))


def delete_mention(db: Session, mention_id: uuid.UUID) -> None:
    service.delete_mention(db, mention_id)
