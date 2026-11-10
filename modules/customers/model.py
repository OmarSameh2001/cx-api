from datetime import date
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Date, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from ..organisations.model import Organisation
    from ..submissions.model import Submission

class Customer(Base):
    """A person who answered an organisation's public forms. Customers never
    log in; each organisation has its own, matched by email."""

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint(
            "organisation_id", "external_id", name="uq_customers_organisation_id_external_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[Optional[str]] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    dob: Mapped[Optional[date]] = mapped_column("DOB", Date)
    gender: Mapped[Optional[str]] = mapped_column(String(16))
    profile_picture: Mapped[Optional[str]] = mapped_column(String(512))

    organisation: Mapped["Organisation"] = relationship(back_populates="customers")
    submissions: Mapped[List["Submission"]] = relationship(back_populates="customer")


# One customer per email per organisation, case-insensitively (emails are
# also stored lowercased).
Index(
    "uq_customers_organisation_id_email",
    Customer.organisation_id,
    func.lower(Customer.email),
    unique=True,
)
