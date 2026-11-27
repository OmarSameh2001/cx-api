"""Which sign-in providers are on.

SSO_PROVIDERS lists them in the order the login page shows them. Each reads:

    <NAME>_CLIENT_ID, <NAME>_CLIENT_SECRET   both needed, or the provider is off
    <NAME>_DISCOVERY_URL                     defaults per provider kind
    <NAME>_LABEL                             the button text (default per kind)
    <NAME>_KIND                              google, microsoft or oidc (default: the name)
    MICROSOFT_TENANT                         common (default), organizations,
                                             consumers, or one directory id
    MICROSOFT_TRUST_PERSONAL_EMAIL           true (default)
"""

import os
import re
import threading
from typing import Optional

from config import SSOEnv

from .base import Provider, ProviderConfig
from .providers import KINDS

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_lock = threading.Lock()
_instances: Optional[dict[str, Provider]] = None


def _env(prefix: str, key: str, default: str = "") -> str:
    return os.getenv(f"{prefix}_{key}", default).strip()


def _build(name: str) -> Optional[Provider]:
    if not _NAME.match(name):
        return None
    prefix = name.upper()
    cls = KINDS.get(_env(prefix, "KIND", name).lower())
    if cls is None:
        return None
    extra = {
        "tenant": _env(prefix, "TENANT"),
        "trust_personal_email": _env(prefix, "TRUST_PERSONAL_EMAIL", "true"),
    }
    config = ProviderConfig(
        name=name,
        client_id=_env(prefix, "CLIENT_ID"),
        client_secret=_env(prefix, "CLIENT_SECRET"),
        discovery_url="",
        label=_env(prefix, "LABEL"),
        extra=extra,
    )
    provider = cls(config)
    provider.name = name
    discovery = _env(prefix, "DISCOVERY_URL") or getattr(provider, "default_discovery_url", "")
    provider.config = ProviderConfig(**{**config.__dict__, "discovery_url": discovery})
    return provider


def _all() -> dict[str, Provider]:
    global _instances
    if _instances is None:
        with _lock:
            if _instances is None:
                built = {}
                for name in SSOEnv.SSO_PROVIDERS:
                    provider = _build(name)
                    if provider is not None:
                        built[name] = provider
                _instances = built
    return _instances


def enabled() -> list[Provider]:
    """Switched-on providers, in SSO_PROVIDERS order."""
    return [p for p in _all().values() if p.configured]


def get(name: str) -> Optional[Provider]:
    """The provider if it is switched on, else None."""
    provider = _all().get(name)
    return provider if provider is not None and provider.configured else None


def reset_for_tests(providers: Optional[dict[str, Provider]] = None) -> None:
    global _instances
    with _lock:
        _instances = providers
