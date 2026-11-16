from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base

# pending: upload link handed out, bytes not confirmed yet
# ready: confirmed in storage and usable
# deleted: removed by a user; the cleanup job deletes the stored object
FileStatus = ("pending", "ready", "deleted")
# image processing after upload (compression, thumbnail)
ProcessingStatus = ("none", "pending", "done", "skipped", "failed")


class StoredFile(Base):
    """One uploaded file. The bytes live with the storage provider under
    `key`; this row is the only way to reach them."""

    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # indexed through ix_files_org_purpose
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(127), nullable=False)
    # declared size while pending, the stored size once ready
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum: Mapped[Optional[str]] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    # extra renditions, e.g. {"thumb": {"key", "content_type", "size", "width", "height"}}
    # none_as_null: Python None is stored as SQL NULL, not JSON null, so
    # "IS NULL" queries mean what they say
    variants: Mapped[Optional[dict]] = mapped_column(JSONB(none_as_null=True))
    processing: Mapped[str] = mapped_column(String(16), nullable=False, server_default="none")
    # a new upload replacing the content, until it's confirmed:
    # {"key", "name", "content_type", "size", "provider"}
    replacement: Mapped[Optional[dict]] = mapped_column(JSONB(none_as_null=True))

    # who uploaded it: an employee, or an anonymous public-form respondent
    # holding the secret whose hash is stored here
    owner_employee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    owner_token_hash: Mapped[Optional[str]] = mapped_column(String(64))
    # form answers: the question it was uploaded for
    # SET NULL, not CASCADE: deleting a form marks its files deleted first, so
    # the cleanup job can still remove their stored bytes
    form_id: Mapped[Optional[int]] = mapped_column(ForeignKey("forms.id", ondelete="SET NULL"), index=True)
    field_id: Mapped[Optional[int]] = mapped_column(Integer)
    # what it belongs to once used, e.g. ("submission", 42)
    attached_type: Mapped[Optional[str]] = mapped_column(String(32))
    attached_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_files_attached", "attached_type", "attached_id"),
        Index("ix_files_org_purpose", "organisation_id", "purpose"),
        # the cleanup job's queue
        Index(
            "ix_files_cleanup",
            "status",
            "created_at",
            postgresql_where=text("status <> 'ready' OR attached_type IS NULL"),
        ),
    )


class FileLimit(Base):
    """A limits override for one purpose. organisation_id NULL: the platform
    default (platform admins); otherwise one organisation's tighter limits
    (its admins). Unset columns inherit from the layer below."""

    __tablename__ = "file_limits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    organisation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    max_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    allowed_types: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String(127)))
    # any ImagePolicy fields: compress, max_side, quality, format, keep_original, thumb_side
    image: Mapped[Optional[dict]] = mapped_column(JSONB(none_as_null=True))
    updated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "uq_file_limits_platform", "purpose", unique=True,
            postgresql_where=text("organisation_id IS NULL"),
        ),
        Index(
            "uq_file_limits_org", "organisation_id", "purpose", unique=True,
            postgresql_where=text("organisation_id IS NOT NULL"),
        ),
    )
