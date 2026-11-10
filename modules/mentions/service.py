import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.tenants.service import ensure_tenant_in_organisation, tenant_in_organisation

from . import repository
from .dto import MentionCreate, MentionUpdate
from .model import Mention


def _ensure_mention(db: Session, mention_id: uuid.UUID, organisation_id: int) -> Mention:
    mention = repository.get_mention(db, mention_id)
    # another organisation's row is reported as missing
    if mention is None or not tenant_in_organisation(db, mention.tenant_id, organisation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mention not found")
    return mention


def list_mentions(db: Session, *, tenant_id: uuid.UUID, organisation_id: int, limit: int, offset: int) -> tuple[list[Mention], int]:
    ensure_tenant_in_organisation(db, tenant_id, organisation_id)
    items = repository.list_mentions(db, tenant_id=tenant_id, limit=limit, offset=offset)
    total = repository.count_mentions(db, tenant_id=tenant_id)
    return items, total


def get_mention(db: Session, mention_id: uuid.UUID, organisation_id: int) -> Mention:
    return _ensure_mention(db, mention_id, organisation_id)


def create_mention(db: Session, *, payload: MentionCreate, organisation_id: int) -> Mention:
    ensure_tenant_in_organisation(db, payload.tenant_id, organisation_id)
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


def update_mention(db: Session, mention_id: uuid.UUID, *, organisation_id: int, payload: MentionUpdate) -> Mention:
    mention = _ensure_mention(db, mention_id, organisation_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return mention
    repository.update_mention(db, mention, data=data)
    db.commit()
    return repository.get_mention(db, mention_id)


def delete_mention(db: Session, mention_id: uuid.UUID, organisation_id: int) -> None:
    mention = _ensure_mention(db, mention_id, organisation_id)
    repository.delete_mention(db, mention)
    db.commit()
