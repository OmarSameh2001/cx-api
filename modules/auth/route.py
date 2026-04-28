from typing import Optional

import jwt
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from config import AuthEnv
from db import get_db

from . import controller, service
from .dto import (
    CustomerLoginResponse,
    CustomerPrincipal,
    EmployeeLoginResponse,
    EmployeePrincipal,
    LoginRequest,
    LogoutResponse,
    Principal,
    TokenResponse,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> Optional[str]:
    if request.client:
        return request.client.host
    return None


def _access_token(
    authorization: Optional[str] = Header(default=None),
    access_cookie: Optional[str] = Cookie(default=None, alias=AuthEnv.ACCESS_COOKIE_NAME),
) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    if access_cookie:
        return access_cookie
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Missing access token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_principal(token: str = Depends(_access_token)) -> Principal:
    try:
        payload = service.decode_access_token(token)
    except jwt.PyJWTError as e:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"Invalid access token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal_type = payload.get("principal")
    if principal_type == "employee":
        return EmployeePrincipal(**payload)
    if principal_type == "customer":
        return CustomerPrincipal(**payload)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown principal type")


def current_employee(p: Principal = Depends(current_principal)) -> EmployeePrincipal:
    if not isinstance(p, EmployeePrincipal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Employee access required")
    return p


def current_customer(p: Principal = Depends(current_principal)) -> CustomerPrincipal:
    if not isinstance(p, CustomerPrincipal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Customer access required")
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
    return controller.employee_login(db, payload, response, user_agent, _client_ip(request))


@router.post("/customer/login", response_model=CustomerLoginResponse)
def customer_login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    user_agent: Optional[str] = Header(default=None, alias="User-Agent"),
):
    return controller.customer_login(db, payload, response, user_agent, _client_ip(request))


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
