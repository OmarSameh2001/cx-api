from typing import Optional

import jwt
from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from sqlalchemy.orm import Session

from common.errors import AppError
from common.rate_limit import client_ip, count_failure, enforce, refuse_if_full
from config import AuthEnv, SSOEnv
from db import get_db

from . import controller, service
from .dto import (
    EmployeeLoginResponse,
    EmployeePrincipal,
    LoginRequest,
    LogoutResponse,
    Preferences,
    PreferencesUpdate,
    Principal,
    TokenResponse,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> Optional[str]:
    # the caller's IP, not the proxy's, as every other sign-in record has it
    return client_ip(request)


def _access_token(
    authorization: Optional[str] = Header(default=None),
    access_cookie: Optional[str] = Cookie(default=None, alias=AuthEnv.ACCESS_COOKIE_NAME),
) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    if access_cookie:
        return access_cookie
    raise AppError(401, "auth.missing_access_token", headers={"WWW-Authenticate": "Bearer"})


def current_principal(token: str = Depends(_access_token)) -> Principal:
    try:
        payload = service.decode_access_token(token)
    except jwt.PyJWTError as e:
        raise AppError(401, "auth.invalid_access_token", headers={"WWW-Authenticate": "Bearer"}, error=e)
    principal_type = payload.get("principal")
    if principal_type == "employee":
        return EmployeePrincipal(**payload)
    # Customers no longer log in (they answer by public link); any customer
    # token still in circulation is refused like an unknown one.
    raise AppError(401, "auth.unknown_principal")


def current_employee(p: Principal = Depends(current_principal)) -> EmployeePrincipal:
    if not isinstance(p, EmployeePrincipal):
        raise AppError(403, "auth.employee_required")
    return p


# def require_permissions(*needed: str):
#     def _checker(p: EmployeePrincipal = Depends(current_employee)) -> EmployeePrincipal:
#         missing = [perm for perm in needed if perm not in p.permissions]
#         if missing:
#             raise HTTPException(
#                 status.HTTP_403_FORBIDDEN, f"Missing permissions: {', '.join(missing)}"
#             )
#         return p

#     return _checker


@router.post("/employee/login", response_model=EmployeeLoginResponse)
def employee_login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    user_agent: Optional[str] = Header(default=None, alias="User-Agent"),
):
    # guessing passwords: every attempt counts per IP; per account only the
    # failures count (so many IPs can't share the work, and signing in often
    # never locks anyone out)
    enforce(f"login-ip:{client_ip(request)}", SSOEnv.LOGINS_PER_MINUTE_PER_IP, 60)
    account = f"login-fail:{payload.email.strip().lower()}"
    window = SSOEnv.LOGIN_FAILURE_WINDOW_MINUTES * 60
    refuse_if_full(account, SSOEnv.LOGIN_FAILURES_PER_EMAIL, window)
    try:
        return controller.employee_login(db, payload, response, user_agent, _client_ip(request))
    except service.AuthError:
        count_failure(account, SSOEnv.LOGIN_FAILURES_PER_EMAIL, window)
        raise


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    refresh_token: Optional[str] = Cookie(default=None, alias=AuthEnv.REFRESH_COOKIE_NAME),
    user_agent: Optional[str] = Header(default=None, alias="User-Agent"),
):
    return controller.refresh(db, refresh_token, response, user_agent, _client_ip(request))


@router.post("/logout", response_model=LogoutResponse)
def logout(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: Optional[str] = Cookie(default=None, alias=AuthEnv.REFRESH_COOKIE_NAME),
):
    return controller.logout(db, refresh_token, response)


@router.post("/logout-all", response_model=LogoutResponse)
def logout_all(
    response: Response,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    return controller.logout_all(db, principal, response)


@router.get("/me", response_model=Principal)
def me(principal: Principal = Depends(current_principal)):
    return principal


@router.get("/session", response_model=EmployeeLoginResponse)
def session(db: Session = Depends(get_db), employee: EmployeePrincipal = Depends(current_employee)):
    """The signed-in employee and their permissions, read fresh."""
    return controller.session(db, employee)


@router.put("/me/preferences", response_model=Preferences)
def update_preferences(
    payload: PreferencesUpdate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_preferences(db, employee, payload)
