import threading
import time
from functools import lru_cache
from typing import Optional, TypeVar

from langchain_core.exceptions import (
    ContextOverflowError,
    ModelInvalidRequestError,
    OutputParserException,
)
from langchain_core.runnables import Runnable
from loguru import logger
from pydantic import BaseModel, ValidationError

from config.AIEnv import AI_PROVIDER_COOLDOWN_SECONDS

from .config import ModelSettings, ProviderConfig, resolve_chain
from .factory import build_model
from .settings import feature_settings


T = TypeVar("T", bound=BaseModel)


class NoProviderAvailable(RuntimeError):
    """Every provider in the chain failed or is cooling down."""


# provider label -> monotonic time it may be tried again; shared by every
# chain in this process so one feature's outage report helps the others
_down_until: dict[str, float] = {}
_lock = threading.Lock()


def _is_down(label: str) -> bool:
    with _lock:
        return _down_until.get(label, 0.0) > time.monotonic()


def _mark_down(label: str) -> None:
    with _lock:
        _down_until[label] = time.monotonic() + AI_PROVIDER_COOLDOWN_SECONDS


_REQUEST_ERROR_STATUSES = {400, 413, 422}


def _is_request_error(e: Exception) -> bool:
    """The provider is fine but refused this request (too long, blocked by a
    safety filter, unsupported parameter). Another provider may accept it,
    but this one must not be cooled down for every other user."""
    if isinstance(e, (ContextOverflowError, ModelInvalidRequestError)):
        return True
    # SDK errors the integration didn't map to a langchain error
    return getattr(e, "status_code", None) in _REQUEST_ERROR_STATUSES


class ProviderChain:
    """Ordered providers for one feature: the first that answers wins.

    Falls over on anything that is the provider's fault (outage, rate limit,
    timeout, bad key, unsupported request). A reply that came back but
    doesn't fit the schema is the model's fault and is raised to the caller,
    which can ask again with the error."""

    def __init__(self, spec: str, settings: ModelSettings):
        self.providers = resolve_chain(spec)
        self.settings = settings
        self._runnables: dict[tuple[str, type], Runnable] = {}
        if not self.providers:
            logger.error("No usable AI provider in '{}'", spec)

    def _structured(self, p: ProviderConfig, schema: type[T]) -> Runnable:
        key = (p.label, schema)
        if key not in self._runnables:
            model = build_model(p, p.settings(self.settings))
            self._runnables[key] = model.with_structured_output(schema, method=p.structured_method)
        return self._runnables[key]

    def _candidates(self) -> list[ProviderConfig]:
        candidates = [p for p in self.providers if not _is_down(p.label)]
        # all cooling down: trying them beats refusing outright
        return candidates or self.providers

    async def ainvoke_structured(self, schema: type[T], messages: list) -> tuple[Optional[T], str]:
        """(parsed reply, label of the provider that answered)."""
        failures = []
        for p in self._candidates():
            try:
                return await self._structured(p, schema).ainvoke(messages), p.label
            except (OutputParserException, ValidationError):
                raise
            except Exception as e:
                if not _is_request_error(e):
                    _mark_down(p.label)
                failures.append(f"{p.label}: {type(e).__name__}")
                logger.warning("AI provider {} failed, trying the next: {}", p.label, e)
        raise NoProviderAvailable("; ".join(failures) or "no AI provider is configured")


@lru_cache
def get_chain(feature: str) -> ProviderChain:
    settings = feature_settings(feature)
    return ProviderChain(settings.providers, settings.model)
