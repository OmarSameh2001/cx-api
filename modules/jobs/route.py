from typing import Optional

from fastapi import APIRouter, Header

from . import controller
from .dto import TickResponse

# Called by a scheduler, not a user: no login, a shared secret instead.
router = APIRouter(prefix="/internal/jobs", tags=["internal"])


# GET too, because Vercel Cron only sends GET
@router.api_route("/tick", methods=["GET", "POST"], response_model=TickResponse)
def tick(authorization: Optional[str] = Header(default=None)):
    return controller.tick(authorization=authorization)
