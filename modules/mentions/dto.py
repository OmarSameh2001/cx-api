import uuid
from datetime import datetime
from typing import Optional, Dict

from pydantic import BaseModel, ConfigDict, Field


class MentionCreate(BaseModel):
    tenant_id: uuid.UUID
    platform: Optional[str] = Field(default=None, max_length=64)
    external_id: Optional[str] = Field(default=None, max_length=255)
    content_text: Optional[str] = None
    url: Optional[str] = Field(default=None, max_length=1024)
    author_handle: Optional[str] = Field(default=None, max_length=255)
    published_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    sentiment_category: Optional[str] = Field(default=None, max_length=32)
    dominant_emotion: Optional[str] = Field(default=None, max_length=32)
    emotion_scores: Optional[Dict] = None
    raw_data: Optional[Dict] = None
    expires_at: Optional[datetime] = None


class MentionUpdate(BaseModel):
    platform: Optional[str] = Field(default=None, max_length=64)
    external_id: Optional[str] = Field(default=None, max_length=255)
    content_text: Optional[str] = None
    url: Optional[str] = Field(default=None, max_length=1024)
    author_handle: Optional[str] = Field(default=None, max_length=255)
    published_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    sentiment_category: Optional[str] = Field(default=None, max_length=32)
    dominant_emotion: Optional[str] = Field(default=None, max_length=32)
    emotion_scores: Optional[Dict] = None
    raw_data: Optional[Dict] = None
    expires_at: Optional[datetime] = None


class MentionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    platform: Optional[str]
    external_id: Optional[str]
    published_at: Optional[datetime]
    sentiment_category: Optional[str]


class MentionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    platform: Optional[str]
    external_id: Optional[str]
    content_text: Optional[str]
    url: Optional[str]
    author_handle: Optional[str]
    published_at: Optional[datetime]
    fetched_at: Optional[datetime]
    sentiment_category: Optional[str]
    dominant_emotion: Optional[str]
    emotion_scores: Optional[Dict]
    raw_data: Optional[Dict]
    expires_at: Optional[datetime]
