from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from ..employees.model import Employee
    from ..submissions.model import Submission
    from ..organisations.model import Organisation

class Form(Base):
    __tablename__ = "forms"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[Optional[str]] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="questionnaire", server_default="questionnaire"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    submitter_type: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String(64)), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    time_limit_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    max_attempts: Mapped[Optional[int]] = mapped_column(Integer)
    results_revealed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"))
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id"), nullable=False
    )
    assigned_to_units: Mapped[Optional[list[int]]] = mapped_column(ARRAY(Integer))
    public_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    sections: Mapped[Optional[list[dict]]] = mapped_column(JSONB, nullable=True)

    organisations: Mapped["Organisation"] = relationship(foreign_keys=[organisation_id])
    creator: Mapped[Optional["Employee"]] = relationship(foreign_keys=[created_by])
    fields: Mapped[List["FormField"]] = relationship(
        back_populates="form", cascade="all, delete-orphan", order_by="FormField.order"
    )
    submissions: Mapped[List["Submission"]] = relationship(back_populates="form")

    __table_args__ = (
        Index("ix_forms_org_active_archived", "organisation_id", "is_active", "is_archived"),
    )


class FormField(Base):
    __tablename__ = "form_fields"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String(255)))
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    right_answer: Mapped[Optional[str]] = mapped_column(Text)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    help_text: Mapped[Optional[str]] = mapped_column(Text)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    score_weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id"), nullable=False, index=True)
    section_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    form: Mapped["Form"] = relationship(back_populates="fields")
