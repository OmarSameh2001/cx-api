import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .model import Keyword


def get_keyword(db: Session, keyword_id: uuid.UUID) -> Keyword | None:
    return db.get(Keyword, keyword_id)


def list_keywords(db: Session, *, tenant_id: uuid.UUID, limit: int = 100, offset: int = 0) -> list[Keyword]:
    stmt = (
        select(Keyword)
        .where(Keyword.tenant_id == tenant_id)
        .order_by(Keyword.phrase)
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def count_keywords(db: Session, *, tenant_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count()).select_from(Keyword).where(Keyword.tenant_id == tenant_id)
    ).scalar_one()


def create_keyword(
    db: Session,
    *,
    phrase: str,
    tenant_id: uuid.UUID,
    is_active: bool = True,
) -> Keyword:
    keyword = Keyword(
        phrase=phrase,
        tenant_id=tenant_id,
        is_active=is_active,
    )
    db.add(keyword)
    db.flush()
    return keyword


def update_keyword(db: Session, keyword: Keyword, *, data: dict) -> Keyword:
    for key, value in data.items():
        setattr(keyword, key, value)
    db.flush()
    return keyword


def delete_keyword(db: Session, keyword: Keyword) -> None:
    db.delete(keyword)
