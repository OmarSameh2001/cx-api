from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class UserIdentity(Base):
    """An outside account (Google, Microsoft...) an employee signs in with.

    Sign-ins are matched on (provider, subject), the provider's stable id,
    never on the email: a provider may let people change it, and some let a
    directory admin set it to anything."""

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_user_identities_provider_subject"),
        # one account per provider per employee
        UniqueConstraint("employee_id", "provider", name="uq_user_identities_employee_provider"),
        Index("ix_user_identities_organisation", "organisation_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    # Microsoft directory id, or Google Workspace domain
    tenant: Mapped[Optional[str]] = mapped_column(String(255))
    # the address the provider gave when it was linked; shown to its owner only
    email: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
