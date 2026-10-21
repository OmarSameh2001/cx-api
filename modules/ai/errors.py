"""Errors every AI endpoint returns, as {"error": code, "detail": message}.
`detail` is shown to the user as is, so it stays plain; specifics go to the log."""

from typing import Literal

from pydantic import BaseModel
from starlette import status

from common.errors import CodedHTTPException


class AIErrorBody(BaseModel):
    error: Literal["ai_unavailable", "ai_generation_failed"]
    detail: str


# for the OpenAPI docs: responses=AI_ERROR_RESPONSES on every AI route
AI_ERROR_RESPONSES = {
    503: {"model": AIErrorBody, "description": "No AI provider answered (ai_unavailable)"},
    502: {"model": AIErrorBody, "description": "No usable result was produced (ai_generation_failed)"},
}


def ai_unavailable() -> CodedHTTPException:
    # every provider is down, rate limited or misconfigured; worth retrying later
    return CodedHTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "The AI service is unavailable right now. Please try again in a moment.",
        code="ai_unavailable",
    )


def ai_generation_failed() -> CodedHTTPException:
    # providers answered but never with a valid result; rephrasing may help
    return CodedHTTPException(
        status.HTTP_502_BAD_GATEWAY,
        "The AI couldn't produce a valid result. Try rephrasing your request.",
        code="ai_generation_failed",
    )
