from langchain_core.language_models import BaseChatModel

from .config import ModelSettings, ProviderConfig


def build_model(p: ProviderConfig, s: ModelSettings) -> BaseChatModel:
    """The langchain chat model for one provider. Imports are local so only
    the packages of providers actually configured need to be installed."""
    common = {"model": p.model, "max_retries": s.max_retries}
    if s.temperature is not None:
        common["temperature"] = s.temperature

    if p.kind == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            api_key=p.api_key, base_url=p.base_url, max_tokens=s.max_tokens,
            timeout=s.timeout, **common,
        )
    if p.kind == "google_genai":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            google_api_key=p.api_key, max_output_tokens=s.max_tokens, timeout=s.timeout, **common
        )

    # openai and every OpenAI-compatible endpoint
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        # local servers ignore the key but the client requires one
        api_key=p.api_key or "not-needed",
        base_url=p.base_url,
        max_tokens=s.max_tokens,
        timeout=s.timeout,
        **common,
    )
