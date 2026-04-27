from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from ..employees.model import Employee
    from ..units.model import Unit

class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    assigned_by: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), nullable=False, index=True)

    employee: Mapped["Employee"] = relationship(
        foreign_keys=[user_id], back_populates="assignments"
    )
    assigner: Mapped[Optional["Employee"]] = relationship(foreign_keys=[assigned_by])
    unit: Mapped["Unit"] = relationship(back_populates="assignments")
