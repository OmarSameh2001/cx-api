import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from ..keywords.model import Keyword
    from ..tenants.model import Tenant


class Mention(Base):
    __tablename__ = "mentions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        default=uuid.uuid4,
    )
    platform: Mapped[Optional[str]] = mapped_column(String(64))
    external_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    content_text: Mapped[Optional[str]] = mapped_column(Text)
    url: Mapped[Optional[str]] = mapped_column(String(1024))
    author_handle: Mapped[Optional[str]] = mapped_column(String(255))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sentiment_category: Mapped[Optional[str]] = mapped_column(String(32))
    dominant_emotion: Mapped[Optional[str]] = mapped_column(String(32))
    emotion_scores: Mapped[Optional[dict]] = mapped_column(JSONB)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="mentions")
    keywords: Mapped[List["Keyword"]] = relationship(
        secondary="mention_keywords", back_populates="mentions"
    )


class MentionKeyword(Base):
    """Junction table linking mentions to matched keywords."""

    __tablename__ = "mention_keywords"

    mention_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mentions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    keyword_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("keywords.id", ondelete="CASCADE"),
        primary_key=True,
    )
