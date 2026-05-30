import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from ..notification_deliveries.model import NotificationDelivery
    from ..tenants.model import Tenant


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        default=uuid.uuid4,
    )
    source_module: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False)
    platform: Mapped[Optional[str]] = mapped_column(String(64))
    threshold_value: Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    time_window_min: Mapped[Optional[int]] = mapped_column(Integer)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="notification_rules")
    deliveries: Mapped[List["NotificationDelivery"]] = relationship(
        back_populates="notification_rule"
    )
