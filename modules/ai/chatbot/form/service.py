from modules.ai.llm import generate_structured
from modules.forms.dto import FormCreate

from .dto import FormGenerateRequest
from .mapper import to_form_create
from .prompts import build_messages
from .schema import GeneratedForm


FEATURE = "form"  # env settings: AI_FORM_PROVIDERS, AI_FORM_MAX_TOKENS...


async def generate_form(request: FormGenerateRequest) -> FormCreate:
    """Build a complete form from a description. The result is the same
    payload the builder sends to POST /forms, already validated by FormCreate;
    a draft FormCreate rejects goes back to the model with the errors."""
    return await generate_structured(
        FEATURE,
        GeneratedForm,
        build_messages(request),
        lambda draft: to_form_create(draft, request),
    )
