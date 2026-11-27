import re
from typing import Iterable, Optional

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from common import i18n, request_context
from config import AuthEnv


DEFAULT_PUBLIC_PATHS: tuple[str, ...] = (
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/docs/oauth2-redirect",
    "/auth/employee/login",
    "/auth/refresh",
    "/auth/logout",
)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Validates the JWT access token on every request before routing.

    Errors (the code stays the same in every language; the detail is in the
    caller's):
      401 token_missing      — no Authorization header and no access cookie
      401 token_malformed    — decode failed (not a JWT / wrong segments)
      401 token_invalid      — signature or claim (issuer/type) mismatch
      401 token_expired      — exp claim is in the past
    """

    def __init__(
        self,
        app: ASGIApp,
        public_paths: Optional[Iterable[str]] = None,
        public_prefixes: Optional[Iterable[str]] = None,
        public_patterns: Optional[Iterable[str]] = None,
    ):
        super().__init__(app)
        self.public_paths = set(public_paths if public_paths is not None else DEFAULT_PUBLIC_PATHS)
        self.public_prefixes = tuple(public_prefixes or ())
        self.public_patterns = tuple(re.compile(p) for p in (public_patterns or ()))

    def _is_public(self, path: str) -> bool:
        if path in self.public_paths:
            return True
        if any(path.startswith(prefix) for prefix in self.public_prefixes):
            return True
        return any(p.fullmatch(path) for p in self.public_patterns)

    def _extract_token(self, request: Request) -> Optional[str]:
        auth = request.headers.get("authorization")
        if auth and auth.lower().startswith("bearer "):
            return auth.split(" ", 1)[1].strip()
        cookie = request.cookies.get(AuthEnv.ACCESS_COOKIE_NAME)
        if cookie:
            return cookie
        return None

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or self._is_public(request.url.path):
            return await call_next(request)

        token = self._extract_token(request)
        if not token:
            return _error(request, "token_missing", "auth.missing_access_token")

        try:
            payload = jwt.decode(
                token,
                AuthEnv.JWT_SECRET,
                algorithms=[AuthEnv.JWT_ALGORITHM],
                issuer=AuthEnv.JWT_ISSUER,
            )
        except jwt.ExpiredSignatureError:
            return _error(request, "token_expired", "auth.token_expired")
        except jwt.InvalidSignatureError:
            return _error(request, "token_invalid", "auth.token_invalid_signature")
        except jwt.DecodeError:
            return _error(request, "token_malformed", "auth.token_malformed")
        except jwt.InvalidTokenError as e:
            return _error(request, "token_invalid", "auth.invalid_access_token", error=str(e))

        if payload.get("typ") != "access":
            return _error(request, "token_invalid", "auth.token_wrong_type")

        request.state.principal = payload
        if payload.get("principal") == "employee":
            request_context.set_actor(payload.get("id"), payload.get("organisation_id"))
        return await call_next(request)


def _error(request: Request, code: str, message: str, **params) -> JSONResponse:
    locale = i18n.request_locale(request)
    return JSONResponse(
        status_code=401,
        content={"error": code, "detail": i18n.t(message, locale, **params)},
        headers={"WWW-Authenticate": "Bearer", "Content-Language": locale},
    )
