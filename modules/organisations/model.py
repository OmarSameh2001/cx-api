from datetime import date
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from ..customers.model import Customer
    from ..employees.model import Employee
    from ..roles.model import Role
    from ..subscriptions.model import SubscriptionPlan
    from ..tenants.model import Tenant
    from ..units.model import Unit

class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # an external image URL (older organisations); logo_file_id wins when set
    logo: Mapped[Optional[str]] = mapped_column(String(512))
    logo_file_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL", use_alter=True, name="fk_organisations_logo_file_id")
    )
    industry: Mapped[Optional[str]] = mapped_column(String(120))
    contact_info: Mapped[Optional[str]] = mapped_column(Text)
    subscription_end: Mapped[Optional[date]] = mapped_column(Date)
    # who may sign in with Google, Microsoft...; see modules/sso/dto.SignInSettings
    sign_in_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}", default=dict
    )

    subscription_plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("subscription_plans.id"), index=True
    )

    subscription_plan: Mapped[Optional["SubscriptionPlan"]] = relationship(
        back_populates="organisations"
    )
    tenant: Mapped[Optional["Tenant"]] = relationship(
        back_populates="organisation", uselist=False
    )
    units: Mapped[List["Unit"]] = relationship(back_populates="organisation")
    employees: Mapped[List["Employee"]] = relationship(back_populates="organisation")
    # ORM cascade (not passive): it also removes each role's role_permissions,
    # whose FK to roles has no ON DELETE.
    roles: Mapped[List["Role"]] = relationship(
        back_populates="organisation", cascade="all, delete-orphan"
    )
    # the database cascades (ON DELETE CASCADE), the ORM must not null the FK
    customers: Mapped[List["Customer"]] = relationship(
        back_populates="organisation", passive_deletes=True
    )
