import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

SeverityName = Literal["debug", "info", "notice", "warning", "error", "critical"]


class AuditQuery(BaseModel):
    """Newest first. Page with `cursor`: pass the previous page's next_cursor."""

    # at least this severe (e.g. "warning" for warnings, errors and critical)
    min_severity: Optional[SeverityName] = None
    # exactly these severities
    severities: Optional[list[SeverityName]] = Field(default=None, max_length=6)
    actions: Optional[list[str]] = Field(default=None, max_length=50)
    # e.g. "form." for everything about forms
    action_prefix: Optional[str] = Field(default=None, max_length=48)
    entity_type: Optional[str] = Field(default=None, max_length=24)
    entity_id: Optional[int] = None
    actor_id: Optional[int] = None
    correlation_id: Optional[uuid.UUID] = None
    # occurred_from <= occurred_at < occurred_to
    occurred_from: Optional[datetime] = None
    occurred_to: Optional[datetime] = None
    cursor: Optional[str] = Field(default=None, max_length=120)
    limit: int = Field(default=50, ge=1, le=200)

    @field_validator("actions")
    @classmethod
    def _short_actions(cls, v):
        if v and any(len(a) > 48 for a in v):
            raise ValueError("actions are at most 48 characters")
        return v

    @model_validator(mode="after")
    def _checks(self):
        if self.entity_id is not None and not self.entity_type:
            raise ValueError("entity_id needs entity_type")
        if self.occurred_from and self.occurred_to and self.occurred_from >= self.occurred_to:
            raise ValueError("occurred_from must be before occurred_to")
        return self


class Change(BaseModel):
    """One changed field. kind "value": old -> new; "set": items added and
    removed; "hidden": personal data, changed but not shown."""

    field: str
    kind: Literal["value", "set", "hidden"]
    old: Any = None
    new: Any = None
    added: list[Any] = []
    removed: list[Any] = []


class AuditEventRead(BaseModel):
    id: int
    occurred_at: datetime
    organisation_id: Optional[int]
    severity: SeverityName
    action: str
    action_label: str
    entity_type: Optional[str]
    entity_id: Optional[int]
    actor_id: Optional[int]
    ip: Optional[str]
    correlation_id: Optional[uuid.UUID]
    changes: list[Change]
    data: Optional[dict[str, Any]]


class AuditPage(BaseModel):
    items: list[AuditEventRead]
    # null on the last page
    next_cursor: Optional[str]
    # current names of the records the page mentions: {"employee": {"3": "Sara Ali"}, "role": {...}}
    names: dict[str, dict[str, str]]


class SeverityInfo(BaseModel):
    name: SeverityName
    level: int


class ActionInfo(BaseModel):
    name: str
    label: str
    severity: SeverityName


class EntityInfo(BaseModel):
    name: str


class AuditCatalogue(BaseModel):
    severities: list[SeverityInfo]
    actions: list[ActionInfo]
    entity_types: list[EntityInfo]
