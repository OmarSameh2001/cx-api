from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from ..organisations.model import Organisation

class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    benefits: Mapped[Optional[str]] = mapped_column(Text)

    organisations: Mapped[List["Organisation"]] = relationship(
        back_populates="subscription_plan"
    )
