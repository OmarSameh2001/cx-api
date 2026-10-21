"""Provider settings: env first, the preset in providers.py as the fallback.

For a provider named NAME (as written in AI_PROVIDERS):
    NAME_KIND               anthropic | openai | google_genai | openai_compatible
    NAME_MODEL              model id (an "NAME:model" entry wins over it)
    NAME_BASE_URL           API url
    NAME_API_KEY            the key itself
    NAME_KEY_ENVS           other env vars holding the key, comma separated
    NAME_NEEDS_KEY          true | false
    NAME_STRUCTURED_METHOD  json_schema | function_calling | json_mode
    NAME_TEMPERATURE, NAME_MAX_TOKENS, NAME_TIMEOUT, NAME_MAX_RETRIES
                            override the feature's settings for this provider
"""

import os
from dataclasses import dataclass, field, replace
from typing import Callable, Optional, TypeVar, get_args

from loguru import logger

from .providers import GENERIC_PRESET, PRESETS, ProviderKind, StructuredMethod


T = TypeVar("T")


@dataclass(frozen=True)
class ModelSettings:
    max_tokens: int
    timeout: float
    max_retries: int
    temperature: Optional[float] = None


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    kind: ProviderKind
    model: str
    # kept out of repr so logging a config can't leak the key
    api_key: Optional[str] = field(repr=False)
    base_url: Optional[str]
    structured_method: StructuredMethod
    # per-provider overrides of the feature's ModelSettings; None keeps it
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}"

    def settings(self, base: ModelSettings) -> ModelSettings:
        overrides = {
            k: v
            for k in ("temperature", "max_tokens", "timeout", "max_retries")
            if (v := getattr(self, k)) is not None
        }
        return replace(base, **overrides)


class ProviderConfigError(ValueError):
    pass


def _env(name: str, suffix: str) -> Optional[str]:
    value = os.getenv(f"{name.upper()}_{suffix}")
    return value.strip() if value and value.strip() else None


def _parsed(name: str, suffix: str, parse: Callable[[str], T]) -> Optional[T]:
    raw = _env(name, suffix)
    if raw is None:
        return None
    try:
        return parse(raw)
    except ValueError as e:
        raise ProviderConfigError(f"{name.upper()}_{suffix}={raw!r} is invalid") from e


def _bool(raw: str) -> bool:
    v = raw.lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ValueError(raw)


def _choice(options: tuple[str, ...]) -> Callable[[str], str]:
    def parse(raw: str) -> str:
        if raw not in options:
            raise ValueError(raw)
        return raw

    return parse


def _build(name: str, pinned_model: str) -> ProviderConfig:
    preset = PRESETS.get(name, GENERIC_PRESET)

    kind = _parsed(name, "KIND", _choice(get_args(ProviderKind))) or preset.kind
    key_envs = _parsed(name, "KEY_ENVS", lambda r: tuple(s.strip() for s in r.split(",") if s.strip()))
    needs_key = _parsed(name, "NEEDS_KEY", _bool)
    if needs_key is None:
        needs_key = preset.needs_key

    api_key = _env(name, "API_KEY")
    for key_env in key_envs or preset.key_envs:
        api_key = api_key or os.getenv(key_env) or None
    model = pinned_model or _env(name, "MODEL") or preset.default_model
    base_url = _env(name, "BASE_URL") or preset.base_url

    default_method = preset.structured_method
    if name not in PRESETS and kind != "openai_compatible":
        # a custom name pointed at a native client: use that client's schema mode
        default_method = "json_schema"

    missing = [
        what
        for what, ok in (
            ("an API key", api_key or not needs_key),
            ("a model", model),
            ("a base url", base_url or kind != "openai_compatible"),
        )
        if not ok
    ]
    if missing:
        raise ProviderConfigError(f"needs {' and '.join(missing)}")

    return ProviderConfig(
        name=name,
        kind=kind,
        model=model,
        api_key=api_key,
        base_url=base_url,
        structured_method=_parsed(name, "STRUCTURED_METHOD", _choice(get_args(StructuredMethod)))
        or default_method,
        temperature=_parsed(name, "TEMPERATURE", float),
        max_tokens=_parsed(name, "MAX_TOKENS", int),
        timeout=_parsed(name, "TIMEOUT", float),
        max_retries=_parsed(name, "MAX_RETRIES", int),
    )


def resolve(entry: str) -> Optional[ProviderConfig]:
    """One AI_PROVIDERS entry ("groq" or "openai:gpt-5") -> its config, or
    None when it can't be used; the reason is logged."""
    name, _, pinned_model = entry.strip().partition(":")
    try:
        return _build(name.lower(), pinned_model.strip())
    except ProviderConfigError as e:
        logger.warning("AI provider '{}' skipped: {}", entry.strip(), e)
        return None


def resolve_chain(spec: str) -> list[ProviderConfig]:
    return [p for p in (resolve(e) for e in spec.split(",") if e.strip()) if p]
