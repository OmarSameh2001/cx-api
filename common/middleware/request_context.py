import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from common import request_context

HEADER = "x-request-id"


def _ip(scope: Scope, headers: dict[bytes, bytes]) -> str | None:
    # the same rule as common.rate_limit.client_ip
    forwarded = headers.get(b"x-forwarded-for")
    client = scope.get("client")
    return request_context.client_ip_from(
        forwarded.decode("latin-1") if forwarded else None, client[0] if client else None
    )


class RequestContextMiddleware:
    """Gives every request a correlation ID (the client's X-Request-ID when
    it's a UUID, else a new one), returns it as X-Request-ID, and makes it and
    the caller's IP available through common.request_context."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        sent = headers.get(HEADER.encode())
        correlation_id = request_context.parse_correlation_id(sent.decode("latin-1") if sent else None)
        correlation_id = correlation_id or uuid.uuid4()
        token = request_context.start(correlation_id, _ip(scope, headers))

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = [
                    *(h for h in message["headers"] if h[0].lower() != HEADER.encode()),
                    (HEADER.encode(), str(correlation_id).encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_context.end(token)
