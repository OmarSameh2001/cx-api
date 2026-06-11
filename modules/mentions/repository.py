import uuid
from datetime import datetime
from typing import Optional, Dict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .model import Mention


def get_mention(db: Session, mention_id: uuid.UUID) -> Mention | None:
    return db.get(Mention, mention_id)


def list_mentions(db: Session, *, tenant_id: uuid.UUID, limit: int = 100, offset: int = 0) -> list[Mention]:
    stmt = (
        select(Mention)
        .where(Mention.tenant_id == tenant_id)
        .order_by(Mention.published_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def count_mentions(db: Session, *, tenant_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count()).select_from(Mention).where(Mention.tenant_id == tenant_id)
    ).scalar_one()


def create_mention(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    platform: Optional[str] = None,
    external_id: Optional[str] = None,
    content_text: Optional[str] = None,
    url: Optional[str] = None,
    author_handle: Optional[str] = None,
    published_at: Optional[datetime] = None,
    fetched_at: Optional[datetime] = None,
    sentiment_category: Optional[str] = None,
    dominant_emotion: Optional[str] = None,
    emotion_scores: Optional[Dict] = None,
    raw_data: Optional[Dict] = None,
    expires_at: Optional[datetime] = None,
) -> Mention:
    mention = Mention(
        tenant_id=tenant_id,
        platform=platform,
        external_id=external_id,
        content_text=content_text,
        url=url,
        author_handle=author_handle,
        published_at=published_at,
        fetched_at=fetched_at,
        sentiment_category=sentiment_category,
        dominant_emotion=dominant_emotion,
        emotion_scores=emotion_scores,
        raw_data=raw_data,
        expires_at=expires_at,
    )
    db.add(mention)
    db.flush()
    return mention


def update_mention(db: Session, mention: Mention, *, data: dict) -> Mention:
    for key, value in data.items():
        setattr(mention, key, value)
    db.flush()
    return mention


def delete_mention(db: Session, mention: Mention) -> None:
    db.delete(mention)
