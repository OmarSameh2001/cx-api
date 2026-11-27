from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from common import i18n


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
    is_admin: bool = False
    is_platform_admin: bool = False
    unit_id: Optional[int] = None
    assigned_unit_ids: list[int] = []
    permissions: list[str] = []
    # the language saved on the account (None: not chosen yet)
    locale: Optional[str] = None


class EmployeeLoginResponse(BaseModel):
    user: EmployeeInfo


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
    # Organisation admin: holds the organisation's system role.
    is_admin: bool = False
    # Platform admin: Employee.is_platform_admin, never granted by a role.
    is_platform_admin: bool = False
    permissions: list[str] = []
    unit_id: Optional[int] = None
    assigned_unit_ids: list[int] = []
    locale: Optional[str] = None


class CustomerPrincipal(BasePrincipal):
    principal: Literal["customer"] = "customer"


Principal = EmployeePrincipal | CustomerPrincipal


class PreferencesUpdate(BaseModel):
    # one of common/i18n LOCALES, or null to follow the browser
    locale: Optional[str] = None

    @field_validator("locale")
    @classmethod
    def _known(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        code = i18n.normalize(value)
        if code is None or code != value.strip().lower():
            raise ValueError(f"locale must be one of: {', '.join(i18n.LOCALES)}")
        return code


class Preferences(BaseModel):
    locale: Optional[str] = None
