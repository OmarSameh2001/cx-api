from typing import Any, Mapping, Optional

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from common import i18n


class CodedHTTPException(HTTPException):
    """HTTPException that also carries a stable machine-readable code.

    The body is {"error": code, "detail": message}, the same shape the auth
    middleware uses, so clients can branch on `error` instead of matching the
    human-readable `detail` text.
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        code: str,
        headers: Optional[dict[str, str]] = None,
        params: Optional[Mapping[str, Any]] = None,
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.params = dict(params or {})


class AppError(CodedHTTPException):
    """An error named by its catalogue code (common/i18n/messages):

        raise AppError(404, "forms.not_found")
        raise AppError(400, "files.too_large", limit=5)

    The caller reads it in their language; `detail` holds the English text
    for logs and tests."""

    def __init__(
        self, status_code: int, code: str, *, headers: Optional[dict[str, str]] = None, **params: Any
    ):
        super().__init__(
            status_code, i18n.t(code, "en", **params), code=code, headers=headers, params=params
        )


def _localized(request: Request, body: dict, status_code: int, headers: Optional[Mapping[str, str]]) -> JSONResponse:
    out_headers = dict(headers or {})
    out_headers["Content-Language"] = i18n.request_locale(request)
    return JSONResponse(status_code=status_code, content=body, headers=out_headers)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Every HTTP error, in the caller's language: {"error": code, "detail": text}.

    A coded error keeps its own code (clients branch on it); a plain English
    detail gets the code of the catalogue entry it matches."""
    locale = i18n.request_locale(request)
    code = getattr(exc, "code", None)
    detail = exc.detail
    body: dict[str, Any]
    if isinstance(detail, str):
        key, text = i18n.translate_detail(detail, locale, code=code, params=getattr(exc, "params", None))
        body = {"detail": text}
        if code or key:
            body["error"] = code or key
    else:
        body = {"detail": jsonable_encoder(detail)}
        if code:
            body["error"] = code
    return _localized(request, body, exc.status_code, getattr(exc, "headers", None))


# kept for the old import name
coded_http_exception_handler = http_exception_handler


def _ctx_params(ctx: Mapping[str, Any]) -> dict[str, str]:
    return {k: str(v) for k, v in ctx.items() if isinstance(v, (str, int, float))}


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422s with each problem in the caller's language.

    The submitted values (`input`) are never echoed back: a login's password
    or a respondent's answers must not reappear in responses or logs. English
    keeps Pydantic's own wording, which is more precise."""
    locale = i18n.request_locale(request)
    problems = []
    for error in exc.errors():
        kind = str(error.get("type", ""))
        msg = str(error.get("msg", ""))
        ctx = error.get("ctx") or {}
        if locale != "en":
            if kind == "value_error":
                raw = str(ctx.get("error", "")) or msg.removeprefix("Value error, ")
                _, msg = i18n.translate_detail(raw, locale)
            elif f"validation.{kind}" in i18n.codes():
                msg = i18n.t(f"validation.{kind}", locale, **_ctx_params(ctx))
        problems.append({"loc": list(error.get("loc", ())), "msg": msg, "type": kind})
    return _localized(
        request, {"error": "validation.invalid_request", "detail": problems}, 422, None
    )
