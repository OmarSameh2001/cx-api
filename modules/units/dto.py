from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class UnitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: Optional[str] = Field(default=None, max_length=64)
    contact_info: Optional[str] = None
    is_active: bool = True
    organisation_id: int
    parent_unit_id: Optional[int] = None
    external_id: Optional[str] = Field(default=None, max_length=64)


class UnitUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    type: Optional[str] = Field(default=None, max_length=64)
    contact_info: Optional[str] = None
    is_active: Optional[bool] = None
    parent_unit_id: Optional[int] = None
    external_id: Optional[str] = Field(default=None, max_length=64)


class UnitSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    type: Optional[str]
    is_active: bool
    organisation_id: int
    parent_unit_id: Optional[int]


class UnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    external_id: Optional[str]
    name: str
    type: Optional[str]
    contact_info: Optional[str]
    is_active: bool
    organisation_id: int
    parent_unit_id: Optional[int]
