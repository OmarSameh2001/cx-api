from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class FailedJob(Base):
    """A background job that ran out of retries. Kept in Postgres rather than
    Redis so the small Redis plan only ever holds the live queue."""

    __tablename__ = "failed_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    args: Mapped[Optional[list]] = mapped_column(JSONB)
    kwargs: Mapped[Optional[dict]] = mapped_column(JSONB)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[Optional[str]] = mapped_column(Text)
    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
