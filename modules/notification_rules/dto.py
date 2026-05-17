import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class NotificationRuleCreate(BaseModel):
    source_module: str = Field(min_length=1, max_length=64)
    rule_type: str = Field(min_length=1, max_length=64)
    platform: Optional[str] = Field(default=None, max_length=64)
    threshold_value: Optional[float] = None
    time_window_min: Optional[int] = None
    email_enabled: bool = False
    in_app_enabled: bool = False
    is_active: bool = True
    tenant_id: uuid.UUID


class NotificationRuleUpdate(BaseModel):
    source_module: Optional[str] = Field(default=None, min_length=1, max_length=64)
    rule_type: Optional[str] = Field(default=None, min_length=1, max_length=64)
    platform: Optional[str] = Field(default=None, max_length=64)
    threshold_value: Optional[float] = None
    time_window_min: Optional[int] = None
    email_enabled: Optional[bool] = None
    in_app_enabled: Optional[bool] = None
    is_active: Optional[bool] = None


class NotificationRuleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source_module: str
    rule_type: str
    is_active: bool
    created_at: datetime


class NotificationRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source_module: str
    rule_type: str
    platform: Optional[str]
    threshold_value: Optional[float]
    time_window_min: Optional[int]
    email_enabled: bool
    in_app_enabled: bool
    is_active: bool
    created_at: datetime
    tenant_id: uuid.UUID
