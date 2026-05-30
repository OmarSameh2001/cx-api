import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import repository
from .dto import MentionCreate, MentionUpdate
from .model import Mention


def _ensure_mention(db: Session, mention_id: uuid.UUID) -> Mention:
    mention = repository.get_mention(db, mention_id)
    if mention is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mention not found")
    return mention


def list_mentions(db: Session, *, tenant_id: uuid.UUID, limit: int, offset: int) -> tuple[list[Mention], int]:
    items = repository.list_mentions(db, tenant_id=tenant_id, limit=limit, offset=offset)
    total = repository.count_mentions(db, tenant_id=tenant_id)
    return items, total


def get_mention(db: Session, mention_id: uuid.UUID) -> Mention:
    return _ensure_mention(db, mention_id)


def create_mention(db: Session, *, payload: MentionCreate) -> Mention:
    mention = repository.create_mention(
        db,
        tenant_id=payload.tenant_id,
        platform=payload.platform,
        external_id=payload.external_id,
        content_text=payload.content_text,
        url=payload.url,
        author_handle=payload.author_handle,
        published_at=payload.published_at,
        fetched_at=payload.fetched_at,
        sentiment_category=payload.sentiment_category,
        dominant_emotion=payload.dominant_emotion,
        emotion_scores=payload.emotion_scores,
        raw_data=payload.raw_data,
        expires_at=payload.expires_at,
    )
    db.commit()
    return repository.get_mention(db, mention.id)


def update_mention(db: Session, mention_id: uuid.UUID, *, payload: MentionUpdate) -> Mention:
    mention = _ensure_mention(db, mention_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return mention
    repository.update_mention(db, mention, data=data)
    db.commit()
    return repository.get_mention(db, mention_id)


def delete_mention(db: Session, mention_id: uuid.UUID) -> None:
    mention = _ensure_mention(db, mention_id)
    repository.delete_mention(db, mention)
    db.commit()
