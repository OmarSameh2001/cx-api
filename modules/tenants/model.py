import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from ..keywords.model import Keyword
    from ..mentions.model import Mention
    from ..notification_deliveries.model import NotificationDelivery
    from ..notification_rules.model import NotificationRule
    from ..organisations.model import Organisation
    from ..platform_configs.model import TenantPlatformConfig


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    retention_days: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    organisation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("organisations.id"), unique=True, index=True
    )

    organisation: Mapped[Optional["Organisation"]] = relationship(
        back_populates="tenant"
    )
    mentions: Mapped[List["Mention"]] = relationship(back_populates="tenant")
    platform_configs: Mapped[List["TenantPlatformConfig"]] = relationship(
        back_populates="tenant"
    )
    keywords: Mapped[List["Keyword"]] = relationship(back_populates="tenant")
    notification_rules: Mapped[List["NotificationRule"]] = relationship(
        back_populates="tenant"
    )
    notification_deliveries: Mapped[List["NotificationDelivery"]] = relationship(
        back_populates="tenant"
    )
