"""One way to call a provider's HTTP API, so every provider classifies
failures the same way (see base.http_error)."""

from typing import Any

import requests

from .base import MessagingError, http_error

TIMEOUT_SECONDS = 15


def post(provider: str, url: str, **kwargs: Any) -> requests.Response:
    kwargs.setdefault("timeout", TIMEOUT_SECONDS)
    try:
        res = requests.post(url, **kwargs)
    except requests.RequestException as exc:  # network trouble: try again later
        raise MessagingError(f"{provider}: {exc}", provider=provider) from exc
    if not res.ok:
        raise http_error(provider, res.status_code, res.text)
    return res


def json_or_empty(res: requests.Response) -> dict:
    try:
        body = res.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
