from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PermissionBase(BaseModel):
    resource: str = Field(min_length=1, max_length=120)
    action: str = Field(min_length=1, max_length=64)


class PermissionCreate(PermissionBase):
    pass


class PermissionRead(PermissionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class RoleBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class RoleCreate(RoleBase):
    is_system: bool = False
    permission_ids: list[int] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)


class RolePermissionsReplace(BaseModel):
    permission_ids: list[int] = Field(default_factory=list)


class RolePermissionsAdd(BaseModel):
    permission_ids: list[int] = Field(min_length=1)


class RoleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    is_system: bool


class RoleRead(BaseModel):
    id: int
    name: str
    is_system: bool
    permissions: list[PermissionRead] = []


class SeedResult(BaseModel):
    created: list[PermissionRead]
    existing: int
