"""What the current request is: its correlation ID, the caller's IP, and who
is signed in. Set by RequestContextMiddleware and the authentication
middleware; read by code that records things about the request (the audit
log) without passing the request around.

Outside a request (background jobs, scripts) `current()` is an empty
context: no correlation ID, no IP, no actor.
"""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass
class RequestContext:
    correlation_id: Optional[uuid.UUID] = None
    ip: Optional[str] = None
    # the signed-in employee, from the access token
    actor_id: Optional[int] = None
    organisation_id: Optional[int] = None


_EMPTY = RequestContext()
_current: ContextVar[Optional[RequestContext]] = ContextVar("request_context", default=None)


def current() -> RequestContext:
    return _current.get() or _EMPTY


def start(correlation_id: uuid.UUID, ip: Optional[str]) -> object:
    """Begins a request's context; returns the token `end()` takes. The
    context object is shared by reference, so middleware further in (auth)
    can fill in the actor and code anywhere below sees it."""
    return _current.set(RequestContext(correlation_id=correlation_id, ip=ip))


def end(token: object) -> None:
    _current.reset(token)  # type: ignore[arg-type]


def set_actor(actor_id: Optional[int], organisation_id: Optional[int]) -> None:
    ctx = _current.get()
    if ctx is not None:
        ctx.actor_id = actor_id
        ctx.organisation_id = organisation_id


def parse_correlation_id(value: Optional[str]) -> Optional[uuid.UUID]:
    """A client-sent X-Request-ID, if it's a UUID; anything else is ignored
    (a new one is made) so arbitrary text never reaches the audit log."""
    if not value:
        return None
    try:
        return uuid.UUID(value.strip())
    except (ValueError, AttributeError):
        return None
