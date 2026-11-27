from typing import Optional

from fastapi import Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from config import AuthEnv, SSOEnv
from modules.auth import controller as auth_controller
from modules.auth.dto import EmployeePrincipal

from . import service
from .dto import IdentityRead, LinkStart, ProvidersResponse, SignInSettings, SignInSettingsRead

# the flow cookie is only ever sent back to /auth/sso/...
_FLOW_PATH = "/auth/sso"


def _redirect(result: service.Redirect, *, clear_flow: bool = False) -> RedirectResponse:
    """A failed start leaves the flow cookie alone (it must not cut short a
    sign-in already under way); the callback always uses it up."""
    response = RedirectResponse(result.url, status_code=303)
    # the callback URL holds a one-use code: never cache it, never pass it on
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    if result.flow_cookie:
        response.set_cookie(
            key=SSOEnv.SSO_FLOW_COOKIE_NAME,
            value=result.flow_cookie,
            max_age=SSOEnv.SSO_FLOW_TTL_SECONDS,
            path=_FLOW_PATH,
            domain=AuthEnv.COOKIE_DOMAIN,
            secure=AuthEnv.COOKIE_SECURE,
            httponly=True,
            # the provider sends people back with a top-level GET, which Lax allows
            samesite="lax",
        )
    elif clear_flow:
        response.delete_cookie(
            key=SSOEnv.SSO_FLOW_COOKIE_NAME, path=_FLOW_PATH, domain=AuthEnv.COOKIE_DOMAIN,
            secure=AuthEnv.COOKIE_SECURE, httponly=True, samesite="lax",
        )
    if result.session:
        access, refresh = result.session
        auth_controller.set_session_cookies(response, access, refresh)
    return response


def providers() -> ProvidersResponse:
    return ProvidersResponse(providers=service.available())


def start(db: Session, provider: str, *, next_path: Optional[str], ticket: Optional[str],
          signed_in_employee_id: Optional[int]) -> RedirectResponse:
    return _redirect(service.start(db, provider, next_path=next_path, ticket=ticket,
                                   signed_in_employee_id=signed_in_employee_id))


def callback(db: Session, provider: str, *, code: Optional[str], state: Optional[str], error: Optional[str],
             flow_cookie: Optional[str], ip: Optional[str], user_agent: Optional[str]) -> RedirectResponse:
    return _redirect(service.callback(db, provider, code=code, state=state, error=error,
                                      flow_cookie=flow_cookie, ip=ip, user_agent=user_agent), clear_flow=True)


def failed(path: str, reason: str) -> RedirectResponse:
    return _redirect(service.Redirect(service.app_url(path, sso_error=reason)))


def link(db: Session, principal: EmployeePrincipal, provider: str, password: str, ip: Optional[str]) -> LinkStart:
    return LinkStart(url=service.link_ticket(db, principal, provider, password=password, ip=ip))


def identities(db: Session, principal: EmployeePrincipal) -> list[IdentityRead]:
    return service.list_identities(db, principal)


def unlink(db: Session, principal: EmployeePrincipal, identity_id: int) -> Response:
    service.unlink(db, principal, identity_id)
    return Response(status_code=204)


def get_settings(db: Session, principal: EmployeePrincipal) -> SignInSettingsRead:
    return service.get_settings(db, principal)


def update_settings(db: Session, principal: EmployeePrincipal, payload: SignInSettings) -> SignInSettingsRead:
    return service.update_settings(db, principal, payload)
