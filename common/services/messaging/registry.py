"""Which providers exist, which are switched on, and sending through them.

Each channel has an ordered provider list in `<CHANNEL>_PROVIDERS`, e.g.

    EMAIL_PROVIDERS=resend,smtp      # Resend first, SMTP if Resend is down
    SMS_PROVIDERS=unifonic,twilio
    WHATSAPP_PROVIDERS=meta
    SLACK_PROVIDERS=webhook

A channel with no providers is off: its messages are skipped, not failed.
A provider that is down or not configured hands the message to the next
one; a message the provider rejects (a bad address) stops there.

To add a provider: write a Provider subclass decorated with
@provider("<channel>", "<name>") in one of PROVIDER_MODULES.
"""

import importlib
import os
import threading
from typing import Callable, Mapping, Optional

from .base import CHANNELS, ConfigError, Message, MessagingError, Provider, ProviderConfig, SendResult

PROVIDER_MODULES = [
    "common.services.messaging.email",
    "common.services.messaging.phone",
    "common.services.messaging.chat",
]
# settings prefix per provider, where it isn't the provider's name
PREFIXES = {
    ("whatsapp", "meta"): "META_WHATSAPP",
    ("slack", "webhook"): "SLACK",
    ("slack", "bot"): "SLACK",
}

_classes: dict[tuple[str, str], type[Provider]] = {}
_instances: dict[tuple[str, str], Provider] = {}
_lock = threading.Lock()
_loaded = False


def provider(channel: str, name: str) -> Callable[[type[Provider]], type[Provider]]:
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")

    def register(cls: type[Provider]) -> type[Provider]:
        cls.name, cls.channel = name, channel
        _classes[(channel, name)] = cls
        return cls

    return register


def _load() -> None:
    global _loaded
    if not _loaded:
        for module in PROVIDER_MODULES:
            importlib.import_module(module)
        _loaded = True


def available(channel: Optional[str] = None) -> dict[str, list[str]]:
    """Every provider this build can use, per channel."""
    _load()
    out: dict[str, list[str]] = {c: [] for c in CHANNELS}
    for c, n in sorted(_classes):
        out[c].append(n)
    return {channel: out[channel]} if channel else out


def configured(channel: str) -> list[str]:
    """The channel's providers, in the order they are tried."""
    raw = os.getenv(f"{channel.upper()}_PROVIDERS", "")
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def is_enabled(channel: str) -> bool:
    return bool(configured(channel))


def get(channel: str, name: str, settings: Optional[Mapping[str, str]] = None) -> Provider:
    """A provider. With `settings` it uses them instead of the environment
    (and isn't cached): e.g. an organisation's own account."""
    _load()
    cls = _classes.get((channel, name))
    if cls is None:
        raise ConfigError(f"unknown {channel} provider {name!r}", provider=name)
    prefix = PREFIXES.get((channel, name), name)
    if settings is not None:
        return cls(ProviderConfig(prefix, settings))
    with _lock:
        if (channel, name) not in _instances:
            _instances[(channel, name)] = cls(ProviderConfig(prefix))
        return _instances[(channel, name)]


def send(
    message: Message,
    *,
    providers: Optional[list[str]] = None,
    settings: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> SendResult:
    """Sends through the first provider that takes the message. `providers`
    overrides the channel's list; `settings` maps a provider name to its own
    settings. Raises MessagingError: permanent if retrying can't help."""
    names = providers if providers is not None else configured(message.channel)
    if not names:
        raise ConfigError(f"no {message.channel} provider is configured")
    errors: list[MessagingError] = []
    for name in names:
        try:
            instance = get(message.channel, name, (settings or {}).get(name))
            return instance.send(message)
        except MessagingError as exc:
            exc.provider = exc.provider or name
            errors.append(exc)
            if exc.permanent and not isinstance(exc, ConfigError):
                break  # the message itself was refused: another provider would refuse it too
    last = errors[-1]
    summary = "; ".join(str(e) for e in errors)
    raise MessagingError(summary, permanent=all(e.permanent for e in errors), provider=last.provider)


def reset_for_tests() -> None:
    _instances.clear()
