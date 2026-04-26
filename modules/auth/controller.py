from typing import Optional

from fastapi import Response
from sqlalchemy.orm import Session

from config import AuthEnv

from . import service
from .dto import (
    CustomerInfo,
    CustomerLoginResponse,
    EmployeeInfo,
    EmployeeLoginResponse,
    LoginRequest,
    LogoutResponse,
    Principal,
    TokenResponse,
)


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AuthEnv.REFRESH_COOKIE_NAME,
        value=token,
        max_age=AuthEnv.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path=AuthEnv.REFRESH_COOKIE_PATH,
        domain=AuthEnv.COOKIE_DOMAIN,
        secure=AuthEnv.COOKIE_SECURE,
        httponly=True,
        samesite=AuthEnv.COOKIE_SAMESITE,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=AuthEnv.REFRESH_COOKIE_NAME,
        path=AuthEnv.REFRESH_COOKIE_PATH,
        domain=AuthEnv.COOKIE_DOMAIN,
    )


def _set_access_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AuthEnv.ACCESS_COOKIE_NAME,
        value=token,
        max_age=AuthEnv.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path=AuthEnv.ACCESS_COOKIE_PATH,
        domain=AuthEnv.COOKIE_DOMAIN,
        secure=AuthEnv.COOKIE_SECURE,
        httponly=True,
        samesite=AuthEnv.COOKIE_SAMESITE,
    )


def _clear_access_cookie(response: Response) -> None:
    response.delete_cookie(
        key=AuthEnv.ACCESS_COOKIE_NAME,
        path=AuthEnv.ACCESS_COOKIE_PATH,
        domain=AuthEnv.COOKIE_DOMAIN,
    )


def employee_login(
    db: Session,
    payload: LoginRequest,
    response: Response,
    user_agent: Optional[str],
    ip: Optional[str],
) -> EmployeeLoginResponse:
    employee, claims, access, refresh, expires_in = service.login_employee(
        db, email=payload.email, password=payload.password, user_agent=user_agent, ip=ip
    )
    _set_refresh_cookie(response, refresh)
    _set_access_cookie(response, access)
    user = EmployeeInfo(
        id=employee.id,
        organisation_id=employee.organisation_id,
        first_name=employee.first_name,
        last_name=employee.last_name,
        email=employee.email,
        role_id=claims.get("role_id"),
        role=claims.get("role"),
        unit_id=claims.get("unit_id"),
        assigned_unit_ids=claims.get("assigned_unit_ids", []),
        permissions=claims.get("permissions", []),
    )
    return EmployeeLoginResponse(user=user)


def customer_login(
    db: Session,
    payload: LoginRequest,
    response: Response,
    user_agent: Optional[str],
    ip: Optional[str],
) -> CustomerLoginResponse:
    customer, _, access, refresh, expires_in = service.login_customer(
        db, email=payload.email, password=payload.password, user_agent=user_agent, ip=ip
    )
    _set_refresh_cookie(response, refresh)
    _set_access_cookie(response, access)
    user = CustomerInfo(
        id=customer.id,
        first_name=customer.first_name,
        last_name=customer.last_name,
        email=customer.email,
    )
    return CustomerLoginResponse(user=user)


def refresh(
    db: Session,
    refresh_token: Optional[str],
    response: Response,
    user_agent: Optional[str],
    ip: Optional[str],
) -> TokenResponse:
    access, new_refresh, expires_in = service.refresh_session(
        db, refresh_token=refresh_token, user_agent=user_agent, ip=ip
    )
    _set_refresh_cookie(response, new_refresh)
    _set_access_cookie(response, access)
    return TokenResponse(access_token=access, expires_in=expires_in)


def logout(db: Session, refresh_token: Optional[str], response: Response) -> LogoutResponse:
    revoked = service.logout(db, refresh_token=refresh_token)
    _clear_refresh_cookie(response)
    _clear_access_cookie(response)
    return LogoutResponse(revoked=revoked)


def logout_all(db: Session, principal: Principal, response: Response) -> LogoutResponse:
    revoked = service.logout_all(
        db, principal_type=principal.principal, principal_id=principal.id
    )
    _clear_refresh_cookie(response)
    _clear_access_cookie(response)
    return LogoutResponse(revoked=revoked)
