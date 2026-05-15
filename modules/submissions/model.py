from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from ..customers.model import Customer
    from ..employees.model import Employee
    from ..forms.model import Form


SubmissionStatus = ("in_progress", "submitted", "late", "expired")


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    answers: Mapped[Optional[dict]] = mapped_column(JSON)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="in_progress", server_default="in_progress"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    results_revealed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    score: Mapped[Optional[float]] = mapped_column(Float)

    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), index=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id"), nullable=False, index=True)

    customer: Mapped[Optional["Customer"]] = relationship(back_populates="submissions")
    employee: Mapped[Optional["Employee"]] = relationship(back_populates="submissions")
    form: Mapped["Form"] = relationship(back_populates="submissions")

    __table_args__ = (
        Index("ix_submissions_form_user_status", "form_id", "user_id", "status"),
        Index("ix_submissions_form_customer_status", "form_id", "customer_id", "status"),
        Index(
            "uq_submissions_one_open_user",
            "form_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'in_progress' AND user_id IS NOT NULL"),
        ),
        Index(
            "uq_submissions_one_open_customer",
            "form_id",
            "customer_id",
            unique=True,
            postgresql_where=text("status = 'in_progress' AND customer_id IS NOT NULL"),
        ),
    )
