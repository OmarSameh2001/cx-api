"""Small signed tokens: a JSON payload, base64url encoded, with an HMAC.

    token = signing.sign({"f": 7, "h": {"branch": "Cairo"}}, purpose="prefill", secret=...)
    data = signing.verify(token, purpose="prefill", secret=...)   # None if forged or expired

The payload is readable by whoever holds the token (it is signed, not
encrypted), so never put a secret in it. `purpose` is part of the MAC, so a
token made for one use is refused for another.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Optional

MAX_TOKEN_LENGTH = 8192


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def mac(secret: str, message: str) -> str:
    return _b64(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest())


def sign(payload: dict[str, Any], *, purpose: str, secret: str, expires_at: Optional[int] = None) -> str:
    body = dict(payload)
    if expires_at is not None:
        body["exp"] = int(expires_at)
    encoded = _b64(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
    return f"{encoded}.{mac(secret, f'{purpose}.{encoded}')}"


def verify(token: Any, *, purpose: str, secret: str, now: Optional[float] = None) -> Optional[dict[str, Any]]:
    if not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH or token.count(".") != 1:
        return None
    encoded, signature = token.split(".")
    if not hmac.compare_digest(signature, mac(secret, f"{purpose}.{encoded}")):
        return None
    try:
        body = json.loads(_unb64(encoded))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    exp = body.get("exp")
    if exp is not None and (not isinstance(exp, int) or (now or time.time()) > exp):
        return None
    return body


def keyed_hash(secret: str, message: str) -> str:
    """A stable, one-way stand-in for an identity (64 hex characters)."""
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
