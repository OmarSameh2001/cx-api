from datetime import date
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ARRAY, Boolean, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from ..assignments.model import Assignment
    from ..organisations.model import Organisation
    from ..roles.model import Role
    from ..submissions.model import Submission
    from ..units.model import Unit

class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    username: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_code: Mapped[Optional[str]] = mapped_column(String(16))
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    dob: Mapped[Optional[date]] = mapped_column("DOB", Date)
    gender: Mapped[Optional[str]] = mapped_column(String(16))
    profile_picture: Mapped[Optional[str]] = mapped_column(String(512))
    refresh_tokens: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), nullable=False, server_default="{}", default=list
    )

    manager_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), index=True)
    unit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("units.id"), index=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id"), nullable=False, index=True
    )
    role_id: Mapped[Optional[int]] = mapped_column(ForeignKey("roles.id"), index=True)

    manager: Mapped[Optional["Employee"]] = relationship(
        remote_side="Employee.id", back_populates="reports"
    )
    reports: Mapped[List["Employee"]] = relationship(back_populates="manager")

    unit: Mapped[Optional["Unit"]] = relationship(back_populates="employees")
    organisation: Mapped["Organisation"] = relationship(back_populates="employees")
    role: Mapped[Optional["Role"]] = relationship(back_populates="employees")

    submissions: Mapped[List["Submission"]] = relationship(back_populates="employee")
    assignments: Mapped[List["Assignment"]] = relationship(
        back_populates="employee", foreign_keys="Assignment.user_id"
    )
