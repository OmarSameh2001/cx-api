"""Sign-in with Google, Microsoft and other OpenID Connect providers (E1.11).

Providers, in the order the login page shows them:

    SSO_PROVIDERS=google,microsoft

Each provider reads <NAME>_CLIENT_ID and <NAME>_CLIENT_SECRET; one without
both is off. See common/services/oidc for the rest (<NAME>_DISCOVERY_URL,
MICROSOFT_TENANT, adding a provider).

Register this callback with each provider (it must match exactly):

    <SSO_CALLBACK_BASE_URL>/auth/sso/<name>/callback
"""

import os

from dotenv import load_dotenv

from config import AuthEnv

load_dotenv()


def _int(name: str, default: str) -> int:
    return int(os.getenv(name, default))


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


SSO_PROVIDERS = [p.strip().lower() for p in os.getenv("SSO_PROVIDERS", "google,microsoft").split(",") if p.strip()]

# this API's public address, which providers send people back to
SSO_CALLBACK_BASE_URL = os.getenv("SSO_CALLBACK_BASE_URL", "http://localhost:8000").strip().rstrip("/")
# the frontend people land on after signing in
SSO_APP_URL = os.getenv("SSO_APP_URL", os.getenv("APP_URL", "http://localhost:3000")).strip().rstrip("/")

# signs the short-lived cookie that ties a callback to the browser that
# started the sign-in, and the tickets that start linking an account
SSO_STATE_SECRET = os.getenv("SSO_STATE_SECRET", AuthEnv.JWT_SECRET + ":sso")
SSO_FLOW_COOKIE_NAME = os.getenv("SSO_FLOW_COOKIE_NAME", "sso_flow")
# how long someone has to finish signing in at the provider
SSO_FLOW_TTL_SECONDS = _int("SSO_FLOW_TTL_SECONDS", "600")
SSO_LINK_TICKET_TTL_SECONDS = _int("SSO_LINK_TICKET_TTL_SECONDS", "120")

# an ID token issued longer ago than this is refused, and clocks may differ by
# SSO_CLOCK_SKEW_SECONDS
SSO_ID_TOKEN_MAX_AGE_SECONDS = _int("SSO_ID_TOKEN_MAX_AGE_SECONDS", "600")
SSO_CLOCK_SKEW_SECONDS = _int("SSO_CLOCK_SKEW_SECONDS", "60")
SSO_HTTP_TIMEOUT_SECONDS = _int("SSO_HTTP_TIMEOUT_SECONDS", "10")
# provider metadata (endpoints, signing keys) is fetched again after this
SSO_METADATA_TTL_SECONDS = _int("SSO_METADATA_TTL_SECONDS", "3600")

# Only for a local test provider: allows http:// provider addresses. Never on
# in production: sign-in would then trust unencrypted answers.
SSO_ALLOW_INSECURE_URLS = _bool("SSO_ALLOW_INSECURE_URLS", "false")

# --- rate limits --------------------------------------------------------------------
# Per IP limits are generous: a whole office may sign in from one address.
SSO_STARTS_PER_MINUTE_PER_IP = _int("SSO_STARTS_PER_MINUTE_PER_IP", "60")
SSO_CALLBACKS_PER_MINUTE_PER_IP = _int("SSO_CALLBACKS_PER_MINUTE_PER_IP", "60")
SSO_LINKS_PER_HOUR_PER_EMPLOYEE = _int("SSO_LINKS_PER_HOUR_PER_EMPLOYEE", "10")
# password sign-in: every attempt counts per IP; per account, only failures
LOGINS_PER_MINUTE_PER_IP = _int("LOGINS_PER_MINUTE_PER_IP", "60")
LOGIN_FAILURES_PER_EMAIL = _int("LOGIN_FAILURES_PER_EMAIL", "10")
LOGIN_FAILURE_WINDOW_MINUTES = _int("LOGIN_FAILURE_WINDOW_MINUTES", "15")
