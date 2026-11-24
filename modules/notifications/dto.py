from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Channel = Literal["in_app", "email", "sms", "whatsapp", "slack"]
Locale = Literal["en", "ar"]


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template: str
    # rendered in the language asked for
    title: str
    body: str
    link: Optional[str]
    created_at: datetime
    read_at: Optional[datetime]


class NotificationPage(BaseModel):
    items: list[NotificationRead]
    # pass as before_id for the next page; null on the last one
    next_before_id: Optional[int]
    unread: int


class UnreadCount(BaseModel):
    unread: int


class MarkedRead(BaseModel):
    marked: int
    unread: int


class TestRequest(BaseModel):
    channels: list[Channel] = Field(default_factory=lambda: ["in_app"], min_length=1, max_length=5)
    locale: Optional[Locale] = None


class ChannelResult(BaseModel):
    channel: Channel
    # sent / failed straight away, queued (will be retried), or skipped
    status: Literal["sent", "failed", "queued", "skipped"]
    provider: Optional[str] = None
    detail: Optional[str] = None


class TestResult(BaseModel):
    results: list[ChannelResult]


class ChannelInfo(BaseModel):
    channel: Channel
    enabled: bool
    # tried in this order
    providers: list[str]
    available: list[str]


class ChannelsInfo(BaseModel):
    channels: list[ChannelInfo]
