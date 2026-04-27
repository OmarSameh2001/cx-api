from datetime import date
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ARRAY, Boolean, Date, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from ..submissions.model import Submission

class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    dob: Mapped[Optional[date]] = mapped_column("DOB", Date)
    gender: Mapped[Optional[str]] = mapped_column(String(16))
    is_auth: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    password: Mapped[Optional[str]] = mapped_column(String(255))
    email_code: Mapped[Optional[str]] = mapped_column(String(16))
    profile_picture: Mapped[Optional[str]] = mapped_column(String(512))
    refresh_tokens: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), nullable=False, server_default="{}", default=list
    )

    submissions: Mapped[List["Submission"]] = relationship(back_populates="customer")
