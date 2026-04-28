from typing import Iterable, Optional

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from config import AuthEnv


DEFAULT_PUBLIC_PATHS: tuple[str, ...] = (
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/docs/oauth2-redirect",
    "/auth/employee/login",
    "/auth/customer/login",
    "/auth/refresh",
    "/auth/logout",
)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Validates the JWT access token on every request before routing.

    Errors:
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
    ):
        super().__init__(app)
        self.public_paths = set(public_paths if public_paths is not None else DEFAULT_PUBLIC_PATHS)
        self.public_prefixes = tuple(public_prefixes or ())

    def _is_public(self, path: str) -> bool:
        if path in self.public_paths:
            return True
        return any(path.startswith(prefix) for prefix in self.public_prefixes)

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
            return _error(401, "token_missing", "Missing access token")

        try:
            payload = jwt.decode(
                token,
                AuthEnv.JWT_SECRET,
                algorithms=[AuthEnv.JWT_ALGORITHM],
                issuer=AuthEnv.JWT_ISSUER,
            )
        except jwt.ExpiredSignatureError:
            return _error(401, "token_expired", "Access token has expired")
        except jwt.InvalidSignatureError:
            return _error(401, "token_invalid", "Access token signature is invalid")
        except jwt.DecodeError:
            return _error(401, "token_malformed", "Access token is malformed")
        except jwt.InvalidTokenError as e:
            return _error(401, "token_invalid", f"Invalid access token: {e}")

        if payload.get("typ") != "access":
            return _error(401, "token_invalid", "Wrong token type")

        request.state.principal = payload
        return await call_next(request)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": code, "detail": message},
        headers={"WWW-Authenticate": "Bearer"},
    )
