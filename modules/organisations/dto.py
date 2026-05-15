from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class OrganisationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    logo: Optional[str] = Field(default=None, max_length=512)
    industry: Optional[str] = Field(default=None, max_length=120)
    contact_info: Optional[str] = None
    subscription_end: Optional[date] = None
    subscription_plan_id: Optional[int] = None
    external_id: Optional[str] = Field(default=None, max_length=64)


class OrganisationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    logo: Optional[str] = Field(default=None, max_length=512)
    industry: Optional[str] = Field(default=None, max_length=120)
    contact_info: Optional[str] = None
    subscription_end: Optional[date] = None
    subscription_plan_id: Optional[int] = None
    external_id: Optional[str] = Field(default=None, max_length=64)


class OrganisationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    industry: Optional[str]
    subscription_end: Optional[date]
    subscription_plan_id: Optional[int]


class OrganisationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    external_id: Optional[str]
    name: str
    logo: Optional[str]
    industry: Optional[str]
    contact_info: Optional[str]
    subscription_end: Optional[date]
    subscription_plan_id: Optional[int]
