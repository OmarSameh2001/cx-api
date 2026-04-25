from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    answers: Mapped[Optional[dict]] = mapped_column(JSON)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    score: Mapped[Optional[float]] = mapped_column(Float)

    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), index=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id"), nullable=False, index=True)

    customer: Mapped[Optional["Customer"]] = relationship(back_populates="submissions")
    employee: Mapped[Optional["Employee"]] = relationship(back_populates="submissions")
    form: Mapped["Form"] = relationship(back_populates="submissions")
