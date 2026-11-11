from typing import Any, Literal, Optional

from pydantic import BaseModel


class JobRunRead(BaseModel):
    name: str
    ok: bool
    attempts: int
    result: Any = None
    error: Optional[str] = None


class TickResponse(BaseModel):
    runner: Literal["inline", "celery"]
    ran: list[JobRunRead] = []
    not_due: list[str] = []
