from typing import List, Optional

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    benefits: Mapped[Optional[str]] = mapped_column(Text)

    organisations: Mapped[List["Organisation"]] = relationship(
        back_populates="subscription_plan"
    )
