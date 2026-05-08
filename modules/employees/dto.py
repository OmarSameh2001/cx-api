from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class EmployeeCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6)
    is_active: bool = True
    external_id: Optional[str] = Field(default=None, max_length=64)
    phone: Optional[str] = Field(default=None, max_length=32)
    dob: Optional[date] = None
    gender: Optional[str] = Field(default=None, max_length=16)
    manager_id: Optional[int] = None
    unit_id: Optional[int] = None
    role_id: Optional[int] = None
    assigned_units: list[int] = Field(default_factory=list)


class EmployeeUpdate(BaseModel):
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    username: Optional[str] = Field(default=None, min_length=1, max_length=120)
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    phone: Optional[str] = Field(default=None, max_length=32)
    dob: Optional[date] = None
    gender: Optional[str] = Field(default=None, max_length=16)
    external_id: Optional[str] = Field(default=None, max_length=64)
    manager_id: Optional[int] = None
    unit_id: Optional[int] = None
    role_id: Optional[int] = None
    assigned_units: Optional[list[int]] = None


class EmployeeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    first_name: str
    last_name: str
    username: str
    email: str
    is_active: bool
    role_id: Optional[int]
    unit_id: Optional[int]
    organisation_id: int
    assigned_units: list[int] = []


class EmployeeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    external_id: Optional[str]
    first_name: str
    last_name: str
    username: str
    email: str
    is_active: bool
    phone: Optional[str]
    dob: Optional[date]
    gender: Optional[str]
    profile_picture: Optional[str]
    manager_id: Optional[int]
    unit_id: Optional[int]
    organisation_id: int
    role_id: Optional[int]
    assigned_units: list[int] = []
