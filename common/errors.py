from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


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
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


async def coded_http_exception_handler(request: Request, exc: CodedHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.code, "detail": exc.detail},
        headers=exc.headers,
    )
