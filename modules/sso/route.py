from typing import Optional

import jwt
from fastapi import APIRouter, Cookie, Depends, Header, Path, Query, Request
from sqlalchemy.orm import Session

from common.errors import CodedHTTPException
from common.rate_limit import client_ip, enforce
from config import AuthEnv, SSOEnv
from db import get_db
from modules.auth import service as auth_service
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import IdentityRead, LinkRequest, LinkStart, ProvidersResponse, SignInSettings, SignInSettingsRead

router = APIRouter(prefix="/auth/sso", tags=["sign-in"])

# public (see main.py): the login page's list, and the two browser redirects
PUBLIC_PATTERNS = (r"/auth/sso/providers", r"/auth/sso/[a-z][a-z0-9_]{0,31}/(?:start|callback)")

ProviderName = Path(pattern=r"^[a-z][a-z0-9_]{0,31}$")


def _signed_in_employee(request: Request) -> Optional[int]:
    """The employee whose access cookie this browser sent, if any (start is
    a public route, so the middleware didn't check it)."""
    token = request.cookies.get(AuthEnv.ACCESS_COOKIE_NAME)
    if not token:
        return None
    try:
        payload = auth_service.decode_access_token(token)
    except jwt.PyJWTError:
        return None
    return payload.get("id") if payload.get("principal") == "employee" else None


@router.get("/providers", response_model=ProvidersResponse)
def providers():
    """The sign-in buttons to show: providers switched on for the app."""
    return controller.providers()


@router.get("/{provider}/start", include_in_schema=False)
def start(
    request: Request,
    provider: str = ProviderName,
    next: Optional[str] = Query(default=None, max_length=512),
    ticket: Optional[str] = Query(default=None, max_length=4096),
    db: Session = Depends(get_db),
):
    """Opened by the browser (a link, not a fetch): sends it on to the provider."""
    try:
        enforce(f"sso-start:{client_ip(request)}", SSOEnv.SSO_STARTS_PER_MINUTE_PER_IP, 60)
    except CodedHTTPException:
        return controller.failed("/profile" if ticket else "/login", "rate_limited")
    return controller.start(
        db, provider, next_path=next, ticket=ticket,
        signed_in_employee_id=_signed_in_employee(request) if ticket else None,
    )


@router.get("/{provider}/callback", include_in_schema=False)
def callback(
    request: Request,
    provider: str = ProviderName,
    code: Optional[str] = Query(default=None, max_length=4096),
    state: Optional[str] = Query(default=None, max_length=512),
    error: Optional[str] = Query(default=None, max_length=256),
    db: Session = Depends(get_db),
    flow_cookie: Optional[str] = Cookie(default=None, alias=SSOEnv.SSO_FLOW_COOKIE_NAME),
    user_agent: Optional[str] = Header(default=None, alias="User-Agent"),
):
    """Where the provider sends the browser back to."""
    ip = client_ip(request)
    try:
        enforce(f"sso-callback:{ip}", SSOEnv.SSO_CALLBACKS_PER_MINUTE_PER_IP, 60)
    except CodedHTTPException:
        return controller.failed("/login", "rate_limited")
    return controller.callback(db, provider, code=code, state=state, error=error,
                               flow_cookie=flow_cookie, ip=ip, user_agent=user_agent)


@router.post("/{provider}/link", response_model=LinkStart)
def link(
    payload: LinkRequest,
    request: Request,
    provider: str = ProviderName,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    """Starts linking an account to the signed-in employee. Needs the
    password; returns the URL the browser must open."""
    return controller.link(db, employee, provider, payload.password, client_ip(request))


@router.get("/identities", response_model=list[IdentityRead])
def identities(db: Session = Depends(get_db), employee: EmployeePrincipal = Depends(current_employee)):
    """The signed-in employee's linked accounts."""
    return controller.identities(db, employee)


@router.delete("/identities/{identity_id}", status_code=204)
def unlink(identity_id: int, db: Session = Depends(get_db), employee: EmployeePrincipal = Depends(current_employee)):
    return controller.unlink(db, employee, identity_id)


@router.get("/settings", response_model=SignInSettingsRead)
def get_settings(db: Session = Depends(get_db), employee: EmployeePrincipal = Depends(current_employee)):
    """The organisation's sign-in rules (organisation admins)."""
    return controller.get_settings(db, employee)


@router.put("/settings", response_model=SignInSettingsRead)
def update_settings(
    payload: SignInSettings,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_settings(db, employee, payload)
