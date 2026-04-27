from datetime import date
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from ..employees.model import Employee
    from ..subscriptions.model import SubscriptionPlan
    from ..units.model import Unit

class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    logo: Mapped[Optional[str]] = mapped_column(String(512))
    industry: Mapped[Optional[str]] = mapped_column(String(120))
    contact_info: Mapped[Optional[str]] = mapped_column(Text)
    subscription_end: Mapped[Optional[date]] = mapped_column(Date)

    subscription_plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("subscription_plans.id"), index=True
    )

    subscription_plan: Mapped[Optional["SubscriptionPlan"]] = relationship(
        back_populates="organisations"
    )
    units: Mapped[List["Unit"]] = relationship(back_populates="organisation")
    employees: Mapped[List["Employee"]] = relationship(back_populates="organisation")
