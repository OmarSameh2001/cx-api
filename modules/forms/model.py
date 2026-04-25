from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class Form(Base):
    __tablename__ = "forms"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[Optional[str]] = mapped_column(String(64))
    type: Mapped[Optional[str]] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"))

    creator: Mapped[Optional["Employee"]] = relationship(foreign_keys=[created_by])
    fields: Mapped[List["FormField"]] = relationship(
        back_populates="form", cascade="all, delete-orphan", order_by="FormField.order"
    )
    submissions: Mapped[List["Submission"]] = relationship(back_populates="form")


class FormField(Base):
    __tablename__ = "form_fields"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    right_answer: Mapped[Optional[str]] = mapped_column(Text)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    help_text: Mapped[Optional[str]] = mapped_column(Text)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    score_weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id"), nullable=False, index=True)

    form: Mapped["Form"] = relationship(back_populates="fields")
