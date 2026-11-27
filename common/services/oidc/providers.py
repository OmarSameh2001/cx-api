"""The providers we know. Each decides which claims prove who someone is.

To add one: subclass Provider, decorate it with @kind("<name>"), and set
<NAME>_CLIENT_ID / _CLIENT_SECRET (and _DISCOVERY_URL if it has no default).
Any other name with <NAME>_KIND=oidc uses the generic rules in base.py.
"""

import re
from typing import Any, Callable

from .base import Identity, OIDCError, Provider, _email, _true

KINDS: dict[str, type[Provider]] = {}


def kind(name: str) -> Callable[[type[Provider]], type[Provider]]:
    def register(cls: type[Provider]) -> type[Provider]:
        KINDS[name] = cls
        return cls

    return register


@kind("oidc")
class GenericProvider(Provider):
    pass


@kind("google")
class GoogleProvider(Provider):
    """Google accounts, personal (Gmail) and Workspace.

    `sub` is the stable id. Google says whether it verified the address
    (`email_verified`); Workspace accounts carry their domain in `hd`."""

    label = "Google"
    default_discovery_url = "https://accounts.google.com/.well-known/openid-configuration"

    def expected_issuer(self, claims: dict[str, Any]) -> str:
        issuer = self.metadata()["issuer"]
        # Google's tokens may name the issuer with or without the scheme
        if claims.get("iss") == "accounts.google.com" and issuer == "https://accounts.google.com":
            return "accounts.google.com"
        return issuer

    def identity(self, claims: dict[str, Any]) -> Identity:
        hosted_domain = claims.get("hd")
        return Identity(
            provider=self.name,
            subject=str(claims["sub"]),
            email=_email(claims.get("email")),
            email_verified=_true(claims.get("email_verified")),
            personal=not hosted_domain,
            tenant=str(hosted_domain).lower() if hosted_domain else None,
        )


# personal Microsoft accounts (Outlook.com, Hotmail, Live) all sign in from this directory
MICROSOFT_CONSUMER_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@kind("microsoft")
class MicrosoftProvider(Provider):
    """Microsoft Entra ID work and school accounts, and personal Microsoft
    accounts (MICROSOFT_TENANT=common, the default).

    The stable id is the directory (`tid`) plus the person in it (`oid`).
    The `email` claim of a work account is set by that directory's admin and
    is NOT proof of ownership, which is how "nOAuth" account takeovers work.
    So a work account's email counts as verified only when Microsoft says
    the domain is verified for that directory (the optional `xms_edov` claim;
    add it under Token configuration in the app registration), or when the
    organisation trusts the directory (sso settings). Personal accounts'
    addresses are verified by Microsoft."""

    label = "Microsoft"

    @property
    def default_discovery_url(self) -> str:
        tenant = self.config.extra.get("tenant") or "common"
        return f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration"

    def expected_issuer(self, claims: dict[str, Any]) -> str:
        tenant = str(claims.get("tid", ""))
        if not _UUID.match(tenant):
            raise OIDCError("bad_token", "no tenant id")
        # the multi-tenant document names the issuer with a {tenantid} placeholder
        return self.metadata()["issuer"].replace("{tenantid}", tenant)

    def identity(self, claims: dict[str, Any]) -> Identity:
        tenant, oid = str(claims.get("tid", "")), str(claims.get("oid", ""))
        if not _UUID.match(tenant) or not oid:
            raise OIDCError("bad_token", "no tenant or object id")
        personal = tenant == MICROSOFT_CONSUMER_TENANT
        trust_personal = self.config.extra.get("trust_personal_email", "true").lower() == "true"
        return Identity(
            provider=self.name,
            subject=f"{tenant}:{oid}",
            email=_email(claims.get("email")),
            email_verified=(personal and trust_personal) or _true(claims.get("xms_edov")) or claims.get("xms_edov") == 1,
            personal=personal,
            tenant=tenant,
        )
