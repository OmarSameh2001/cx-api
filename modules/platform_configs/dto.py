import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PlatformConfigCreate(BaseModel):
    platform: str = Field(min_length=1, max_length=64)
    is_enabled: bool = True
    tenant_id: uuid.UUID


class PlatformConfigUpdate(BaseModel):
    platform: Optional[str] = Field(default=None, min_length=1, max_length=64)
    is_enabled: Optional[bool] = None
    fetch_cursor: Optional[str] = Field(default=None, max_length=512)
    last_fetched_at: Optional[datetime] = None


class PlatformConfigSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    platform: str
    is_enabled: bool
    last_fetched_at: Optional[datetime]


class PlatformConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    platform: str
    is_enabled: bool
    last_fetched_at: Optional[datetime]
    fetch_cursor: Optional[str]
    tenant_id: uuid.UUID
