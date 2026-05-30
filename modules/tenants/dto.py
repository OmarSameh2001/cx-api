import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=1, max_length=255)
    retention_days: Optional[int] = Field(default=None, ge=1)
    is_active: bool = True
    organisation_id: Optional[int] = None


class TenantUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email: Optional[str] = Field(default=None, min_length=1, max_length=255)
    retention_days: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None
    organisation_id: Optional[int] = None


class TenantSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    email: str
    is_active: bool
    created_at: datetime


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    email: str
    retention_days: Optional[int]
    is_active: bool
    created_at: datetime
    organisation_id: Optional[int]
