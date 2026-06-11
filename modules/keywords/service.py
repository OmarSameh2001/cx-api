import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import repository
from .dto import KeywordCreate, KeywordUpdate
from .model import Keyword


def _ensure_keyword(db: Session, keyword_id: uuid.UUID) -> Keyword:
    keyword = repository.get_keyword(db, keyword_id)
    if keyword is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Keyword not found")
    return keyword


def list_keywords(db: Session, *, tenant_id: uuid.UUID, limit: int, offset: int) -> tuple[list[Keyword], int]:
    items = repository.list_keywords(db, tenant_id=tenant_id, limit=limit, offset=offset)
    total = repository.count_keywords(db, tenant_id=tenant_id)
    return items, total


def get_keyword(db: Session, keyword_id: uuid.UUID) -> Keyword:
    return _ensure_keyword(db, keyword_id)


def create_keyword(db: Session, *, payload: KeywordCreate) -> Keyword:
    keyword = repository.create_keyword(
        db,
        phrase=payload.phrase,
        tenant_id=payload.tenant_id,
        is_active=payload.is_active,
    )
    db.commit()
    return repository.get_keyword(db, keyword.id)


def update_keyword(db: Session, keyword_id: uuid.UUID, *, payload: KeywordUpdate) -> Keyword:
    keyword = _ensure_keyword(db, keyword_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return keyword
    repository.update_keyword(db, keyword, data=data)
    db.commit()
    return repository.get_keyword(db, keyword_id)


def delete_keyword(db: Session, keyword_id: uuid.UUID) -> None:
    keyword = _ensure_keyword(db, keyword_id)
    repository.delete_keyword(db, keyword)
    db.commit()
