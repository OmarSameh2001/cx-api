"""Signing in with Google, Microsoft... (E1.11).

    GET  /auth/sso/{provider}/start      the browser goes to the provider
    GET  /auth/sso/{provider}/callback   and comes back here

What keeps it safe:
- The flow cookie (httpOnly, signed, 10 minutes) ties the callback to the
  browser that started it: `state` must match it, the ID token's `nonce`
  must match it, and the PKCE verifier only lives in it. A callback link
  sent to someone else, or replayed, fails.
- The code is swapped for tokens server to server; the ID token is checked
  in full (common/services/oidc/base.py). Provider tokens are discarded.
- People are matched on the provider's stable id. A first sign-in links to
  the one employee with the same email only when the provider vouches for
  the email (Google `email_verified`; Microsoft personal accounts, `xms_edov`
  or a directory the organisation trusts), never for platform admins, and
  never when that employee already has another account of that provider.
- There is no sign-up: no employee, no session.
- Every refusal looks the same to the person (it never says whether an
  account exists); the audit log keeps the real reason.
- Linking from the profile needs the password, a one-use ticket, and the
  same signed-in browser.
- Rate limits per IP on start and callback; every outcome is audited.
"""

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote, urlencode

import jwt
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.errors import AppError, CodedHTTPException
from common.rate_limit import enforce
from common.services import oidc
from config import AuthEnv, SSOEnv
from modules.audit import service as audit
from modules.auth import service as auth_service
from modules.auth.dto import EmployeePrincipal

from . import repository
from .dto import IdentityRead, ProviderInfo, SignInSettings, SignInSettingsRead
from .model import UserIdentity

FLOW_TYPE = "sso_flow"
TICKET_TYPE = "sso_link"
_ALGORITHM = "HS256"


# --- small helpers -----------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def redirect_uri(provider_name: str) -> str:
    return f"{SSOEnv.SSO_CALLBACK_BASE_URL}/auth/sso/{provider_name}/callback"


def app_url(path: str, **query: str) -> str:
    url = f"{SSOEnv.SSO_APP_URL}{path}"
    return f"{url}?{urlencode(query)}" if query else url


def safe_next(value: Optional[str]) -> str:
    """Only a path inside the app, so a sign-in link can't send people to
    another site afterwards ("//evil.example", "/\\evil.example", "https:...")."""
    if not value or len(value) > 512 or not value.startswith("/") or value.startswith(("/login", "/sso/")):
        return "/"
    if value.startswith("//") or "\\" in value or any(ord(c) < 33 or ord(c) == 127 for c in value):
        return "/"
    return value


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _sign(payload: dict[str, Any], ttl: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {**payload, "iss": AuthEnv.JWT_ISSUER, "iat": now, "exp": now + ttl},
        SSOEnv.SSO_STATE_SECRET,
        algorithm=_ALGORITHM,
    )


def _unsign(token: Optional[str], expected_type: str) -> Optional[dict[str, Any]]:
    if not token or len(token) > 4096:
        return None
    try:
        payload = jwt.decode(
            token, SSOEnv.SSO_STATE_SECRET, algorithms=[_ALGORITHM], issuer=AuthEnv.JWT_ISSUER,
            options={"require": ["exp", "iat", "typ"]},
        )
    except jwt.PyJWTError:
        return None
    return payload if payload.get("typ") == expected_type else None


def _settings(db: Session, organisation_id: int) -> SignInSettings:
    organisation = repository.get_organisation(db, organisation_id)
    raw = (organisation.sign_in_settings if organisation is not None else None) or {}
    try:
        return SignInSettings.model_validate(raw)
    except ValueError:
        # stored settings that no longer validate: fall back to the strictest
        logger.warning("sso: organisation {} has invalid sign-in settings", organisation_id)
        return SignInSettings(providers={}, allow_personal_accounts=False, link_by_email=False)


def _is_microsoft(provider: oidc.Provider) -> bool:
    return isinstance(provider, oidc.KINDS["microsoft"])


class Refused(Exception):
    """A sign-in that must not go ahead. `reason` goes to the audit log;
    `public` is the only thing the person is told."""

    def __init__(self, reason: str, public: str = "failed", employee=None):
        super().__init__(reason)
        self.reason, self.public, self.employee = reason, public, employee


# --- the login page ---------------------------------------------------------------------


def available() -> list[ProviderInfo]:
    return [ProviderInfo(name=p.name, label=p.label) for p in oidc.enabled()]


# --- starting -----------------------------------------------------------------------------


@dataclass
class Redirect:
    url: str
    # the flow cookie to set (None: clear it)
    flow_cookie: Optional[str] = None
    # a new session to set (access, refresh)
    session: Optional[tuple[str, str]] = None


def start(
    db: Session,
    provider_name: str,
    *,
    next_path: Optional[str],
    ticket: Optional[str],
    signed_in_employee_id: Optional[int],
) -> Redirect:
    provider = oidc.get(provider_name)
    mode, employee_id = "login", None
    failure_page = "/login"
    if ticket is not None:
        failure_page = "/profile"
        claims = _unsign(ticket, TICKET_TYPE)
        # the ticket must be used once, by the browser of the person it was
        # made for: a copied link is useless anywhere else
        if (
            claims is None
            or claims.get("provider") != provider_name
            or signed_in_employee_id is None
            or claims.get("employee_id") != signed_in_employee_id
        ):
            return Redirect(app_url(failure_page, sso_error="link_failed"))
        try:
            enforce(f"sso-ticket:{claims.get('jti')}", 1, SSOEnv.SSO_LINK_TICKET_TTL_SECONDS + 60)
        except CodedHTTPException:
            return Redirect(app_url(failure_page, sso_error="link_failed"))
        mode, employee_id = "link", signed_in_employee_id

    if provider is None:
        return Redirect(app_url(failure_page, sso_error="unavailable"))

    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    try:
        url = provider.authorization_url(
            redirect_uri=redirect_uri(provider.name), state=state, nonce=nonce,
            code_challenge=_pkce_challenge(verifier),
        )
    except oidc.OIDCError as exc:
        logger.warning("sso {}: can't start ({}: {})", provider_name, exc.reason, exc)
        return Redirect(app_url(failure_page, sso_error="unavailable"))
    flow = _sign(
        {
            "typ": FLOW_TYPE, "provider": provider.name, "state": state, "nonce": nonce,
            "verifier": verifier, "next": safe_next(next_path), "mode": mode, "employee_id": employee_id,
        },
        SSOEnv.SSO_FLOW_TTL_SECONDS,
    )
    return Redirect(url, flow_cookie=flow)


# --- coming back ----------------------------------------------------------------------------


def callback(
    db: Session,
    provider_name: str,
    *,
    code: Optional[str],
    state: Optional[str],
    error: Optional[str],
    flow_cookie: Optional[str],
    ip: Optional[str],
    user_agent: Optional[str],
) -> Redirect:
    flow = _unsign(flow_cookie, FLOW_TYPE)
    if flow is None or flow.get("provider") != provider_name:
        # no flow from this browser: expired, another browser, or forged
        auth_service.record_failed_login(db, ip, None, reason="no_flow", method=provider_name)
        return Redirect(app_url("/login", sso_error="expired"))
    linking = flow.get("mode") == "link"
    failure_page = "/profile" if linking else "/login"

    try:
        if not state or not hmac.compare_digest(str(state), str(flow["state"])):
            raise Refused("state_mismatch")
        if error:
            raise Refused(f"provider_error:{str(error)[:40]}",
                          public="cancelled" if error == "access_denied" else "failed")
        if not code or len(code) > 4096:
            raise Refused("no_code")
        provider = oidc.get(provider_name)
        if provider is None:
            raise Refused("provider_unavailable", public="unavailable")
        try:
            id_token = provider.exchange(
                code=code, redirect_uri=redirect_uri(provider.name), code_verifier=flow["verifier"]
            )
            identity = provider.identity(provider.verify(id_token, nonce=flow["nonce"]))
        except oidc.OIDCError as exc:
            public = "unavailable" if exc.reason in ("provider_unreachable", "provider_misconfigured") else "failed"
            raise Refused(exc.reason, public=public) from exc

        if linking:
            return _link(db, provider, identity, employee_id=flow.get("employee_id"))
        return _login(db, provider, identity, next_path=flow.get("next"), ip=ip, user_agent=user_agent)
    except Refused as refused:
        db.rollback()
        logger.info("sso {}: refused ({})", provider_name, refused.reason)
        if linking:
            if refused.employee is not None:
                audit.record(db, "auth.identity_link_failed", entity=refused.employee,
                             data={"method": provider_name, "reason": refused.reason})
                db.commit()
            public = refused.public if refused.public in ("cancelled", "unavailable", "in_use", "already_linked") else "link_failed"
        elif refused.reason == "account_disabled":
            audit.record(db, "auth.login_blocked", entity=refused.employee, actor_id=None, ip=ip,
                         data={"method": provider_name})
            db.commit()
            public = refused.public
        else:
            auth_service.record_failed_login(
                db, ip, refused.employee, reason=refused.reason, method=provider_name
            )
            public = refused.public
        return Redirect(app_url(failure_page, sso_error=public))


def _check_policy(settings: SignInSettings, provider: oidc.Provider, identity: oidc.Identity,
                  *, linked_email: Optional[str], employee) -> None:
    if not settings.provider_enabled(provider.name):
        raise Refused("provider_disabled_for_organisation", employee=employee)
    if identity.personal and not settings.allow_personal_accounts:
        raise Refused("personal_account_not_allowed", employee=employee)
    if settings.allowed_email_domains:
        email = identity.email or linked_email or ""
        if email.rpartition("@")[2] not in settings.allowed_email_domains:
            raise Refused("email_domain_not_allowed", employee=employee)
    if _is_microsoft(provider) and not identity.personal and settings.trusted_microsoft_tenants:
        if identity.tenant not in settings.trusted_microsoft_tenants:
            raise Refused("tenant_not_trusted", employee=employee)


def _find_by_email(db: Session, provider: oidc.Provider, identity: oidc.Identity):
    """The one employee a first sign-in may link to, or Refused."""
    if not identity.email:
        raise Refused("no_email")
    candidates = repository.employees_with_email(db, identity.email)
    if not candidates:
        raise Refused("unknown_account")
    if len(candidates) > 1:
        raise Refused("ambiguous_email")
    employee = candidates[0]
    settings = _settings(db, employee.organisation_id)
    trusted_tenant = (
        _is_microsoft(provider) and identity.tenant is not None
        and identity.tenant in settings.trusted_microsoft_tenants
    )
    if not (identity.email_verified or trusted_tenant):
        raise Refused("email_not_verified", employee=employee)
    if not settings.link_by_email:
        raise Refused("link_by_email_disabled", employee=employee)
    # the most powerful accounts link only by hand, from the profile
    if employee.is_platform_admin:
        raise Refused("platform_admin_must_link", employee=employee)
    if repository.identity_of(db, employee.id, provider.name) is not None:
        # already linked to another account of this provider: an address
        # match must not add a second way in
        raise Refused("other_account_linked", employee=employee)
    return employee, settings


def _login(db: Session, provider: oidc.Provider, identity: oidc.Identity, *,
           next_path: Optional[str], ip: Optional[str], user_agent: Optional[str]) -> Redirect:
    row = repository.get_identity(db, provider.name, identity.subject)
    if row is not None:
        employee = repository.get_employee(db, row.employee_id)
        if employee is None:
            raise Refused("unknown_account")
        settings = _settings(db, employee.organisation_id)
    else:
        employee, settings = _find_by_email(db, provider, identity)

    if not employee.is_active:
        raise Refused("account_disabled", employee=employee)
    _check_policy(settings, provider, identity, linked_email=row.email if row else None, employee=employee)

    if row is None:
        row = _add_identity(db, employee, provider, identity, how="email")
    row.last_used_at = _now()
    employee, _claims, access, refresh, _ = auth_service.issue_session(
        db, employee, user_agent=user_agent, ip=ip, method=provider.name
    )
    return Redirect(app_url("/sso/complete", next=safe_next(next_path)), session=(access, refresh))


def _link(db: Session, provider: oidc.Provider, identity: oidc.Identity, *, employee_id: Optional[int]) -> Redirect:
    employee = repository.get_employee(db, employee_id) if employee_id else None
    if employee is None or not employee.is_active:
        raise Refused("account_unavailable")
    existing = repository.get_identity(db, provider.name, identity.subject)
    if existing is not None:
        if existing.employee_id != employee.id:
            raise Refused("identity_in_use", public="in_use", employee=employee)
        return Redirect(app_url("/profile", sso_linked=provider.name))
    if repository.identity_of(db, employee.id, provider.name) is not None:
        raise Refused("already_linked", public="already_linked", employee=employee)
    settings = _settings(db, employee.organisation_id)
    _check_policy(settings, provider, identity, linked_email=None, employee=employee)
    _add_identity(db, employee, provider, identity, how="profile")
    db.commit()
    return Redirect(app_url("/profile", sso_linked=provider.name))


def _add_identity(db: Session, employee, provider: oidc.Provider, identity: oidc.Identity, *, how: str) -> UserIdentity:
    row = UserIdentity(
        organisation_id=employee.organisation_id, employee_id=employee.id, provider=provider.name,
        subject=identity.subject, tenant=identity.tenant, email=identity.email, created_at=_now(),
    )
    try:
        repository.add_identity(db, row)
    except IntegrityError as exc:
        # linked at the same moment by another request
        raise Refused("identity_in_use", public="in_use", employee=employee) from exc
    audit.record(db, "auth.identity_linked", entity=employee, actor_id=employee.id,
                 data={"method": provider.name, "how": how, "personal": identity.personal})
    notify_owner(db, employee, "security.identity_linked", provider=provider.label, email=identity.email or "")
    return row


def notify_owner(db: Session, employee, template: str, **params: Any) -> None:
    """Tells the person (in the app and by email) that a way into their
    account was added or removed, so a link they didn't make stands out."""
    from modules.notifications import service as notifications

    try:
        notifications.notify(
            db, organisation_id=employee.organisation_id, recipient_ids=[employee.id],
            template=template, params=params, link="/profile", channels=("in_app", "email"),
        )
    except Exception as exc:  # a message must never block signing in
        logger.warning("sso: couldn't notify employee {} ({})", employee.id, exc)


# --- linking from the profile ---------------------------------------------------------------


def link_ticket(db: Session, principal: EmployeePrincipal, provider_name: str, *, password: str,
                ip: Optional[str]) -> str:
    enforce(f"sso-link:{principal.id}", SSOEnv.SSO_LINKS_PER_HOUR_PER_EMPLOYEE, 3600)
    provider = oidc.get(provider_name)
    if provider is None:
        raise AppError(404, "sso.provider_unavailable")
    employee = repository.get_employee(db, principal.id)
    if employee is None or not employee.is_active:
        raise AppError(401, "auth.account_unavailable")
    if not auth_service.verify_password(password, employee.password):
        auth_service.record_failed_login(db, ip, employee, reason="wrong_password", method=f"link:{provider.name}")
        raise AppError(403, "auth.wrong_password")
    if repository.identity_of(db, employee.id, provider.name) is not None:
        raise AppError(409, "sso.already_linked", provider=provider.label)
    if not _settings(db, employee.organisation_id).provider_enabled(provider.name):
        raise AppError(403, "sso.provider_unavailable")
    ticket = _sign(
        {"typ": TICKET_TYPE, "employee_id": employee.id, "provider": provider.name, "jti": secrets.token_urlsafe(16)},
        SSOEnv.SSO_LINK_TICKET_TTL_SECONDS,
    )
    return f"{SSOEnv.SSO_CALLBACK_BASE_URL}/auth/sso/{quote(provider.name)}/start?ticket={quote(ticket)}"


def _label(name: str) -> str:
    provider = oidc.get(name)
    return provider.label if provider is not None else name.title()


def list_identities(db: Session, principal: EmployeePrincipal) -> list[IdentityRead]:
    return [
        IdentityRead(id=r.id, provider=r.provider, label=_label(r.provider), email=r.email,
                     created_at=r.created_at, last_used_at=r.last_used_at)
        for r in repository.identities_of(db, principal.id)
    ]


def unlink(db: Session, principal: EmployeePrincipal, identity_id: int) -> None:
    row = repository.get_owned_identity(db, principal.id, identity_id)
    if row is None:
        raise AppError(404, "sso.identity_not_found")
    employee = repository.get_employee(db, principal.id)
    repository.delete_identity(db, row)
    if employee is not None:
        audit.record(db, "auth.identity_unlinked", entity=employee, data={"method": row.provider})
        notify_owner(db, employee, "security.identity_unlinked", provider=_label(row.provider))
    db.commit()


# --- organisation settings -------------------------------------------------------------------


def _ensure_admin(principal: EmployeePrincipal) -> None:
    if not (principal.is_admin or principal.is_platform_admin):
        raise AppError(403, "sso.settings_admin_only")


def get_settings(db: Session, principal: EmployeePrincipal) -> SignInSettingsRead:
    _ensure_admin(principal)
    settings = _settings(db, principal.organisation_id)
    return SignInSettingsRead(**settings.model_dump(), available_providers=available())


def update_settings(db: Session, principal: EmployeePrincipal, payload: SignInSettings) -> SignInSettingsRead:
    _ensure_admin(principal)
    organisation = repository.get_organisation(db, principal.organisation_id)
    if organisation is None:
        raise AppError(404, "organisations.not_found")
    before = organisation.sign_in_settings or {}
    after = payload.model_dump()
    organisation.sign_in_settings = after
    if before != after:
        # settings hold no personal data, so both versions are kept
        audit.record(db, "organisation.sign_in_settings_changed", entity=organisation,
                     data={"before": before, "after": after})
    db.commit()
    return SignInSettingsRead(**after, available_providers=available())
