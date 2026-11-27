"""One OpenID Connect provider: where to send people, and checking what
comes back.

The flow (authorization code with PKCE) runs on the server:
  1. authorization_url(): send the browser to the provider with a random
     `state`, `nonce` and PKCE challenge.
  2. exchange(): swap the returned code for tokens, server to server, with
     the client secret and the PKCE verifier.
  3. verify(): check the ID token's signature against the provider's
     published keys, and its issuer, audience, expiry, age and nonce.
  4. identity(): read who it is. Subclasses decide which claims to trust.

Provider tokens are never stored or sent to the browser.
"""

import hmac
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from loguru import logger

from config import SSOEnv

# asymmetric only: an HS256 token would be "signed" with our public client
# id/secret, and "none" isn't signed at all
ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512")


class OIDCError(Exception):
    """Sign-in with a provider failed. `reason` is for the audit log, never
    shown to the person (it can reveal whether an account exists)."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    client_id: str
    client_secret: str
    discovery_url: str
    label: str
    extra: dict[str, str]


@dataclass(frozen=True)
class Identity:
    provider: str
    # never changes for this person at this provider (Google `sub`,
    # Microsoft `tid:oid`); accounts are matched on it, never on email
    subject: str
    email: Optional[str]
    # the provider vouches that the person owns `email`
    email_verified: bool
    # a personal account (Gmail, Outlook.com), not a work or school one
    personal: bool
    # Microsoft directory id, or Google Workspace domain
    tenant: Optional[str]


def _check_url(url: str, what: str) -> str:
    parsed = urlparse(url or "")
    if parsed.scheme == "https" and parsed.netloc:
        return url
    if parsed.scheme == "http" and parsed.netloc and SSOEnv.SSO_ALLOW_INSECURE_URLS:
        return url
    raise OIDCError("provider_misconfigured", f"{what} must be an https URL: {url!r}")


class Provider:
    name: str = ""
    label: str = ""
    scopes: tuple[str, ...] = ("openid", "email", "profile")
    # sent to the provider's sign-in page
    authorize_params: dict[str, str] = {"prompt": "select_account"}

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.label = config.label or self.label or config.name.title()
        self._metadata: Optional[dict[str, Any]] = None
        self._metadata_at = 0.0
        self._jwks: Optional[jwt.PyJWKClient] = None
        self._lock = threading.Lock()

    # --- configuration ---------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self.config.client_id and self.config.client_secret and self.config.discovery_url)

    def metadata(self) -> dict[str, Any]:
        """The provider's discovery document, cached for SSO_METADATA_TTL_SECONDS."""
        with self._lock:
            fresh = time.monotonic() - self._metadata_at < SSOEnv.SSO_METADATA_TTL_SECONDS
            if self._metadata is not None and fresh:
                return self._metadata
            url = _check_url(self.config.discovery_url, "discovery URL")
            try:
                response = httpx.get(url, timeout=SSOEnv.SSO_HTTP_TIMEOUT_SECONDS, follow_redirects=False)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise OIDCError("provider_unreachable", f"discovery failed: {exc}") from exc
            for key in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
                if not isinstance(data.get(key), str):
                    raise OIDCError("provider_misconfigured", f"discovery has no {key}")
                if key != "issuer":
                    _check_url(data[key], key)
            if data.get("jwks_uri") != (self._metadata or {}).get("jwks_uri"):
                self._jwks = jwt.PyJWKClient(
                    data["jwks_uri"], cache_keys=True, lifespan=SSOEnv.SSO_METADATA_TTL_SECONDS,
                    timeout=SSOEnv.SSO_HTTP_TIMEOUT_SECONDS,
                )
            self._metadata, self._metadata_at = data, time.monotonic()
            return data

    # --- the flow ----------------------------------------------------------------------

    def authorization_url(self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str) -> str:
        endpoint = self.metadata()["authorization_endpoint"]
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            **self.authorize_params,
        }
        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}{urlencode(params)}"

    def exchange(self, *, code: str, redirect_uri: str, code_verifier: str) -> str:
        """The ID token for `code`, straight from the provider's token endpoint."""
        endpoint = self.metadata()["token_endpoint"]
        try:
            response = httpx.post(
                endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
                timeout=SSOEnv.SSO_HTTP_TIMEOUT_SECONDS,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise OIDCError("provider_unreachable", f"token request failed: {exc}") from exc
        if response.status_code != 200:
            # the body may say why (invalid_grant: a reused or expired code); never log tokens
            try:
                error = response.json().get("error")
            except ValueError:
                error = None
            logger.info("sso {}: token endpoint answered {} ({})", self.name, response.status_code, error)
            raise OIDCError("code_rejected", f"token endpoint answered {response.status_code}")
        try:
            id_token = response.json().get("id_token")
        except ValueError:
            id_token = None
        if not isinstance(id_token, str) or not id_token:
            raise OIDCError("no_id_token")
        return id_token

    def expected_issuer(self, claims: dict[str, Any]) -> str:
        return self.metadata()["issuer"]

    def verify(self, id_token: str, *, nonce: str) -> dict[str, Any]:
        """The ID token's claims, once everything about it checks out."""
        metadata = self.metadata()
        supported = metadata.get("id_token_signing_alg_values_supported") or ["RS256"]
        algorithms = [a for a in supported if a in ALLOWED_ALGORITHMS]
        if not algorithms:
            raise OIDCError("provider_misconfigured", "no safe signing algorithm")
        try:
            header = jwt.get_unverified_header(id_token)
            if header.get("alg") not in algorithms:
                raise OIDCError("bad_token", f"unexpected algorithm {header.get('alg')!r}")
            assert self._jwks is not None
            key = self._jwks.get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                key.key,
                algorithms=algorithms,
                audience=self.config.client_id,
                leeway=SSOEnv.SSO_CLOCK_SKEW_SECONDS,
                options={"require": ["iss", "sub", "aud", "exp", "iat"]},
            )
        except OIDCError:
            raise
        except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
            raise OIDCError("bad_token", str(exc)) from exc

        if claims.get("iss") != self.expected_issuer(claims):
            raise OIDCError("bad_token", "wrong issuer")
        # with several audiences, the token must have been issued to us
        audiences = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
        if (len(audiences) > 1 or "azp" in claims) and claims.get("azp") != self.config.client_id:
            raise OIDCError("bad_token", "issued to another client")
        if time.time() - float(claims["iat"]) > SSOEnv.SSO_ID_TOKEN_MAX_AGE_SECONDS + SSOEnv.SSO_CLOCK_SKEW_SECONDS:
            raise OIDCError("bad_token", "token too old")
        if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(claims["nonce"], nonce):
            raise OIDCError("bad_token", "nonce mismatch")
        return claims

    def identity(self, claims: dict[str, Any]) -> Identity:
        """Generic OpenID Connect: `sub`, and `email` only if `email_verified`."""
        return Identity(
            provider=self.name,
            subject=str(claims["sub"]),
            email=_email(claims.get("email")),
            email_verified=_true(claims.get("email_verified")),
            personal=False,
            tenant=None,
        )


def _true(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _email(value: Any) -> Optional[str]:
    if not isinstance(value, str) or "@" not in value or len(value) > 255:
        return None
    return value.strip().lower()
