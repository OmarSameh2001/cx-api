import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.tenants.service import ensure_tenant_in_organisation, tenant_in_organisation

from . import repository
from .dto import KeywordCreate, KeywordUpdate
from .model import Keyword


def _ensure_keyword(db: Session, keyword_id: uuid.UUID, organisation_id: int) -> Keyword:
    keyword = repository.get_keyword(db, keyword_id)
    # another organisation's row is reported as missing
    if keyword is None or not tenant_in_organisation(db, keyword.tenant_id, organisation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Keyword not found")
    return keyword


def list_keywords(db: Session, *, tenant_id: uuid.UUID, organisation_id: int, limit: int, offset: int) -> tuple[list[Keyword], int]:
    ensure_tenant_in_organisation(db, tenant_id, organisation_id)
    items = repository.list_keywords(db, tenant_id=tenant_id, limit=limit, offset=offset)
    total = repository.count_keywords(db, tenant_id=tenant_id)
    return items, total


def get_keyword(db: Session, keyword_id: uuid.UUID, organisation_id: int) -> Keyword:
    return _ensure_keyword(db, keyword_id, organisation_id)


def create_keyword(db: Session, *, payload: KeywordCreate, organisation_id: int) -> Keyword:
    ensure_tenant_in_organisation(db, payload.tenant_id, organisation_id)
    keyword = repository.create_keyword(
        db,
        phrase=payload.phrase,
        tenant_id=payload.tenant_id,
        is_active=payload.is_active,
    )
    db.commit()
    return repository.get_keyword(db, keyword.id)


def update_keyword(db: Session, keyword_id: uuid.UUID, *, organisation_id: int, payload: KeywordUpdate) -> Keyword:
    keyword = _ensure_keyword(db, keyword_id, organisation_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return keyword
    repository.update_keyword(db, keyword, data=data)
    db.commit()
    return repository.get_keyword(db, keyword_id)


def delete_keyword(db: Session, keyword_id: uuid.UUID, organisation_id: int) -> None:
    keyword = _ensure_keyword(db, keyword_id, organisation_id)
    repository.delete_keyword(db, keyword)
    db.commit()
