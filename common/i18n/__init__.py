"""Backend messages in every language the app speaks (T1.10.5).

    common/i18n/locales.py                      the languages (add one there)
    common/i18n/messages/<locale>/<category>.json   the words, one file per area

A message's code is "<category>.<name>", e.g. "auth.invalid_credentials".
New code raises a code:

    from common.errors import AppError
    raise AppError(404, "forms.not_found")
    raise AppError(400, "files.too_large", limit_mb=5)

Older raises of plain English text are matched to their en entry, so every
error body is {"error": code, "detail": text in the caller's language}. The
caller's language is the first we speak in Accept-Language, then the
language saved on their account (the token's `locale`), then DEFAULT_LOCALE.
"""

from typing import Any, Mapping, Optional

from starlette.requests import HTTPConnection

from . import catalogue
from .catalogue import codes, entries, match
from .locales import DEFAULT_LOCALE, LOCALES, Locale, from_accept_language, normalize

__all__ = [
    "DEFAULT_LOCALE", "LOCALES", "Locale", "codes", "entries", "from_accept_language", "match",
    "normalize", "request_locale", "t", "translate_detail",
]


def request_locale(request: Optional[HTTPConnection]) -> str:
    if request is None:
        return DEFAULT_LOCALE
    chosen = from_accept_language(request.headers.get("accept-language"))
    if chosen:
        return chosen
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, dict):
        saved = normalize(principal.get("locale"))
        if saved:
            return saved
    return DEFAULT_LOCALE


def t(code: str, locale: Optional[str] = None, **params: Any) -> str:
    """The message for `code` in `locale`; the code itself if it is unknown."""
    return catalogue.text(code, locale, params) or code


def translate_detail(
    detail: str, locale: str, *, code: Optional[str] = None, params: Optional[Mapping[str, Any]] = None
) -> tuple[Optional[str], str]:
    """(catalogue code, text in `locale`) for an error's English detail.

    A known `code` is used as is; otherwise the detail is matched against the
    en catalogue. Unknown text is returned unchanged with no code."""
    if code and code in catalogue.codes():
        return code, catalogue.text(code, locale, params) or detail
    found = catalogue.match(detail)
    if found is None:
        return None, detail
    matched, matched_params = found
    return matched, catalogue.text(matched, locale, matched_params) or detail
