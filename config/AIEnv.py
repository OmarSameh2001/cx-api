import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


# Provider order, first is primary and the rest are fallbacks, e.g.
# "anthropic,openai,gemini,groq". An entry may pin a model: "openai:gpt-5".
# Each provider reads NAME_API_KEY, NAME_MODEL, NAME_BASE_URL...; see
# modules/ai/llm/config.py. Any unknown name is an OpenAI-compatible endpoint.
AI_PROVIDERS = os.getenv("AI_PROVIDERS", "anthropic")
# a provider that just failed is skipped for this long, so an outage costs
# one timeout instead of one per request
AI_PROVIDER_COOLDOWN_SECONDS = float(os.getenv("AI_PROVIDER_COOLDOWN_SECONDS", "60"))
# SDK-level retries on the same provider before falling over to the next
AI_PROVIDER_MAX_RETRIES = int(os.getenv("AI_PROVIDER_MAX_RETRIES", "1"))

# Per-feature settings. Each reads AI_<FEATURE>_<NAME> first (AI_FORM_PROVIDERS,
# AI_FORM_MAX_TOKENS...), then AI_<NAME> for all features, then this default.
FEATURE_DEFAULTS: dict[str, Optional[str]] = {
    "PROVIDERS": AI_PROVIDERS,
    "MAX_TOKENS": "8000",
    "TIMEOUT_SECONDS": "45",
    # unset keeps each provider's default (some reasoning models reject any other)
    "TEMPERATURE": None,
    # total model calls per request, including the ones that fix a rejected draft
    "MAX_ATTEMPTS": "3",
    # no new attempt starts after this, so a request can't hang for minutes
    "DEADLINE_SECONDS": "120",
}


def feature_env(feature: str, name: str) -> Optional[str]:
    for key in (f"AI_{feature.upper()}_{name}", f"AI_{name}"):
        value = os.getenv(key)
        if value and value.strip():
            return value.strip()
    return FEATURE_DEFAULTS[name]
