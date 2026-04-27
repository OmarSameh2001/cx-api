from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from ..assignments.model import Assignment
    from ..employees.model import Employee
    from ..organisations.model import Organisation

class Unit(Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[Optional[str]] = mapped_column(String(64))
    contact_info: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id"), nullable=False, index=True
    )
    parent_unit_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("units.id"), index=True
    )

    organisation: Mapped["Organisation"] = relationship(back_populates="units")
    parent_unit: Mapped[Optional["Unit"]] = relationship(
        remote_side="Unit.id", back_populates="child_units"
    )
    child_units: Mapped[List["Unit"]] = relationship(back_populates="parent_unit")

    employees: Mapped[List["Employee"]] = relationship(back_populates="unit")
    assignments: Mapped[List["Assignment"]] = relationship(back_populates="unit")
