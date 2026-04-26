from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field


PrincipalType = Literal["employee", "customer"]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class EmployeeInfo(BaseModel):
    id: int
    organisation_id: int
    first_name: str
    last_name: str
    email: EmailStr
    role_id: Optional[int] = None
    role: Optional[str] = None
    unit_id: Optional[int] = None
    assigned_unit_ids: list[int] = []
    permissions: list[str] = []


class CustomerInfo(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: EmailStr


class EmployeeLoginResponse(BaseModel):
    user: EmployeeInfo


class CustomerLoginResponse(BaseModel):
    user: CustomerInfo


class LogoutResponse(BaseModel):
    revoked: int


class BasePrincipal(BaseModel):
    principal: PrincipalType
    id: int
    jti: str


class EmployeePrincipal(BasePrincipal):
    principal: Literal["employee"] = "employee"
    organisation_id: int
    role_id: Optional[int] = None
    role: Optional[str] = None
    permissions: list[str] = []
    unit_id: Optional[int] = None
    assigned_unit_ids: list[int] = []


class CustomerPrincipal(BasePrincipal):
    principal: Literal["customer"] = "customer"


Principal = EmployeePrincipal | CustomerPrincipal
