import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class KeywordCreate(BaseModel):
    phrase: str = Field(min_length=1, max_length=255)
    is_active: bool = True
    tenant_id: uuid.UUID


class KeywordUpdate(BaseModel):
    phrase: Optional[str] = Field(default=None, min_length=1, max_length=255)
    is_active: Optional[bool] = None


class KeywordSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    phrase: str
    is_active: bool
    created_at: datetime


class KeywordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    phrase: str
    is_active: bool
    created_at: datetime
    tenant_id: uuid.UUID
