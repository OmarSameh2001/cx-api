import uuid

from sqlalchemy.orm import Session

from common.dto import Page

from . import service
from .dto import KeywordCreate, KeywordRead, KeywordSummary, KeywordUpdate


def list_keywords(db: Session, *, tenant_id: uuid.UUID, organisation_id: int, limit: int, offset: int) -> Page[KeywordSummary]:
    items, total = service.list_keywords(db, tenant_id=tenant_id, organisation_id=organisation_id, limit=limit, offset=offset)
    summaries = [KeywordSummary.model_validate(k) for k in items]
    return Page(items=summaries, total=total, limit=limit, offset=offset)


def get_keyword(db: Session, keyword_id: uuid.UUID, organisation_id: int) -> KeywordRead:
    return KeywordRead.model_validate(service.get_keyword(db, keyword_id, organisation_id))


def create_keyword(db: Session, payload: KeywordCreate, organisation_id: int) -> KeywordRead:
    return KeywordRead.model_validate(service.create_keyword(db, payload=payload, organisation_id=organisation_id))


def update_keyword(db: Session, keyword_id: uuid.UUID, payload: KeywordUpdate, organisation_id: int) -> KeywordRead:
    return KeywordRead.model_validate(service.update_keyword(db, keyword_id, organisation_id=organisation_id, payload=payload))


def delete_keyword(db: Session, keyword_id: uuid.UUID, organisation_id: int) -> None:
    service.delete_keyword(db, keyword_id, organisation_id)
