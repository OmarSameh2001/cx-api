"""Signing people in with OpenID Connect providers (Google, Microsoft...).

    from common.services import oidc
    provider = oidc.get("google")
    url = provider.authorization_url(redirect_uri=..., state=..., nonce=..., code_challenge=...)
    claims = provider.verify(provider.exchange(code=..., redirect_uri=..., code_verifier=...), nonce=...)
    who = provider.identity(claims)

See base.py for the flow and its checks, providers.py for what each
provider's claims prove, and registry.py for the settings.
"""

from .base import Identity, OIDCError, Provider, ProviderConfig
from .providers import MICROSOFT_CONSUMER_TENANT, KINDS, kind
from .registry import enabled, get, reset_for_tests

__all__ = [
    "Identity", "KINDS", "MICROSOFT_CONSUMER_TENANT", "OIDCError", "Provider", "ProviderConfig",
    "enabled", "get", "kind", "reset_for_tests",
]
