from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from config.AIEnv import AI_PROVIDER_MAX_RETRIES, feature_env

from .config import ModelSettings


@dataclass(frozen=True)
class FeatureSettings:
    feature: str
    providers: str
    model: ModelSettings
    max_attempts: int
    deadline_seconds: float


def _float(value: Optional[str]) -> Optional[float]:
    return float(value) if value is not None else None


@lru_cache
def feature_settings(feature: str) -> FeatureSettings:
    """Settings for one AI feature ("form", "summary"...), from the env."""
    env = lambda name: feature_env(feature, name)  # noqa: E731
    return FeatureSettings(
        feature=feature,
        providers=env("PROVIDERS"),
        model=ModelSettings(
            max_tokens=int(env("MAX_TOKENS")),
            timeout=float(env("TIMEOUT_SECONDS")),
            max_retries=AI_PROVIDER_MAX_RETRIES,
            temperature=_float(env("TEMPERATURE")),
        ),
        max_attempts=int(env("MAX_ATTEMPTS")),
        deadline_seconds=float(env("DEADLINE_SECONDS")),
    )
