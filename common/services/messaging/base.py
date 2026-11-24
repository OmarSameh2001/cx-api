"""The messaging provider interface, shared by every channel.

A provider sends one Message on one channel (email, sms, whatsapp, slack)
and says whether a failure is worth retrying. Providers read their settings
from a ProviderConfig: environment variables by default, or any mapping
(e.g. one organisation's own account) passed in instead.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

CHANNELS = ("email", "sms", "whatsapp", "slack")


@dataclass(frozen=True)
class Message:
    channel: str
    # email address, phone number in E.164 (+201001234567), or for Slack a
    # webhook URL or channel; empty means the provider's configured default
    to: str
    text: str
    subject: Optional[str] = None
    html: Optional[str] = None
    locale: str = "en"
    # a reference the provider sends back (our delivery id), and anything a
    # provider-specific feature needs (e.g. a WhatsApp template name)
    reference: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SendResult:
    provider: str
    message_id: Optional[str] = None


class MessagingError(Exception):
    """`permanent`: retrying won't help (bad address, rejected by the
    provider, missing settings). Otherwise it's worth another try, possibly
    with the next provider."""

    def __init__(self, message: str, *, permanent: bool = False, provider: Optional[str] = None):
        super().__init__(message)
        self.permanent = permanent
        self.provider = provider


class ConfigError(MessagingError):
    """The provider isn't set up (missing settings, unknown name). Never the
    message's fault, so the next provider gets a chance."""

    def __init__(self, message: str, *, provider: Optional[str] = None):
        super().__init__(message, permanent=True, provider=provider)


class ProviderConfig:
    """Settings for one provider, read as `<PREFIX>_<KEY>`. With `values`
    the mapping is used instead of the environment (keys without prefix)."""

    def __init__(self, prefix: str, values: Optional[Mapping[str, Any]] = None):
        self.prefix = prefix.upper()
        self.values = values

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        if self.values is not None:
            value = self.values.get(key, self.values.get(key.lower()))
        else:
            value = os.getenv(f"{self.prefix}_{key}")
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return str(value).strip()

    def require(self, *keys: str) -> list[str]:
        missing = [k for k in keys if self.get(k) is None]
        if missing:
            names = ", ".join(f"{self.prefix}_{k}" for k in missing)
            raise ConfigError(f"{names} must be set", provider=self.prefix.lower())
        return [self.get(k) for k in keys]  # type: ignore[misc]

    def int(self, key: str, default: int) -> int:
        value = self.get(key)
        return int(value) if value is not None else default

    def bool(self, key: str, default: bool) -> bool:
        value = self.get(key)
        return default if value is None else value.lower() in ("1", "true", "yes", "on")


class Provider(ABC):
    name: str
    channel: str

    def __init__(self, config: ProviderConfig):
        self.config = config

    @abstractmethod
    def send(self, message: Message) -> SendResult: ...


def http_error(provider: str, status: int, body: str) -> MessagingError:
    """4xx (except timeouts and rate limits) is the request's fault: retrying
    won't help. 5xx, 408 and 429 are worth another try."""
    permanent = 400 <= status < 500 and status not in (408, 429)
    return MessagingError(f"{provider}: HTTP {status}: {body[:300]}", permanent=permanent, provider=provider)
