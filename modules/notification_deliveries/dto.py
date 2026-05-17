import uuid
from datetime import datetime
from typing import Optional, Dict

from pydantic import BaseModel, ConfigDict, Field


class NotificationDeliveryCreate(BaseModel):
    source_module: str = Field(min_length=1, max_length=64)
    context_type: Optional[str] = Field(default=None, max_length=64)
    context_id: Optional[uuid.UUID] = None
    payload: Optional[Dict] = None
    channel: str = Field(min_length=1, max_length=32)
    recipient: str = Field(min_length=1, max_length=255)
    status: str = Field(min_length=1, max_length=32)
    sent_at: Optional[datetime] = None
    notification_rule_id: uuid.UUID
    tenant_id: uuid.UUID


class NotificationDeliveryUpdate(BaseModel):
    status: Optional[str] = Field(default=None, min_length=1, max_length=32)
    sent_at: Optional[datetime] = None


class NotificationDeliverySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    channel: str
    recipient: str
    status: str
    sent_at: Optional[datetime]


class NotificationDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source_module: str
    context_type: Optional[str]
    context_id: Optional[uuid.UUID]
    payload: Optional[Dict]
    channel: str
    recipient: str
    status: str
    sent_at: Optional[datetime]
    notification_rule_id: uuid.UUID
    tenant_id: uuid.UUID
