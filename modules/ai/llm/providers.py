"""Built-in providers. Adding one is a new entry here; nothing else changes.

`kind` picks the client: the three with their own langchain package, or
"openai_compatible" for everything that speaks the OpenAI chat API.
`structured_method` is how structured output is requested from it:
"json_schema" where the API enforces a schema, "function_calling" where only
tool calls are reliable.

These are only fallbacks: every field can be overridden from the env, see
config.py for the variable names.
"""

from dataclasses import dataclass
from typing import Literal, Optional


ProviderKind = Literal["anthropic", "openai", "google_genai", "openai_compatible"]
StructuredMethod = Literal["json_schema", "function_calling", "json_mode"]


@dataclass(frozen=True)
class ProviderPreset:
    kind: ProviderKind
    default_model: Optional[str]
    base_url: Optional[str] = None
    # env vars checked for the key, in order
    key_envs: tuple[str, ...] = ()
    needs_key: bool = True
    structured_method: StructuredMethod = "json_schema"


PRESETS: dict[str, ProviderPreset] = {
    # major vendors
    "anthropic": ProviderPreset("anthropic", "claude-sonnet-5-5", key_envs=("ANTHROPIC_API_KEY",)),
    "openai": ProviderPreset("openai", "gpt-5-mini", key_envs=("OPENAI_API_KEY",)),
    "gemini": ProviderPreset(
        "google_genai", "gemini-flash-latest", key_envs=("GEMINI_API_KEY", "GOOGLE_API_KEY")
    ),
    "mistral": ProviderPreset(
        "openai_compatible", "mistral-large-latest", "https://api.mistral.ai/v1",
        key_envs=("MISTRAL_API_KEY",),
    ),
    "xai": ProviderPreset(
        "openai_compatible", "grok-4", "https://api.x.ai/v1", key_envs=("XAI_API_KEY",)
    ),
    "deepseek": ProviderPreset(
        "openai_compatible", "deepseek-chat", "https://api.deepseek.com/v1",
        key_envs=("DEEPSEEK_API_KEY",), structured_method="function_calling",
    ),
    "cohere": ProviderPreset(
        "openai_compatible", "command-a-03-2025", "https://api.cohere.ai/compatibility/v1",
        key_envs=("COHERE_API_KEY",), structured_method="function_calling",
    ),
    # free tiers / open-model hosts
    "groq": ProviderPreset(
        "openai_compatible", "llama-3.3-70b-versatile", "https://api.groq.com/openai/v1",
        key_envs=("GROQ_API_KEY",), structured_method="function_calling",
    ),
    "openrouter": ProviderPreset(
        "openai_compatible", "meta-llama/llama-3.3-70b-instruct:free", "https://openrouter.ai/api/v1",
        key_envs=("OPENROUTER_API_KEY",), structured_method="function_calling",
    ),
    "together": ProviderPreset(
        "openai_compatible", "meta-llama/Llama-3.3-70B-Instruct-Turbo", "https://api.together.xyz/v1",
        key_envs=("TOGETHER_API_KEY",), structured_method="function_calling",
    ),
    "cerebras": ProviderPreset(
        "openai_compatible", "llama-3.3-70b", "https://api.cerebras.ai/v1",
        key_envs=("CEREBRAS_API_KEY",), structured_method="function_calling",
    ),
    "github": ProviderPreset(
        "openai_compatible", "openai/gpt-4.1-mini", "https://models.github.ai/inference",
        key_envs=("GITHUB_TOKEN",),
    ),
    # local, no key
    "ollama": ProviderPreset(
        "openai_compatible", "llama3.1", "http://localhost:11434/v1", needs_key=False
    ),
}

# Any name not above is a generic OpenAI-compatible endpoint (vLLM, LM Studio,
# Azure-style gateways, LiteLLM, a company proxy...). It must set
# <NAME>_BASE_URL and <NAME>_MODEL; the key is optional.
GENERIC_PRESET = ProviderPreset(
    "openai_compatible", None, needs_key=False, structured_method="function_calling"
)
