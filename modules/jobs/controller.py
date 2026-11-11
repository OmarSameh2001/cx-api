import hmac
from typing import Optional

from fastapi import HTTPException, status

from config import RedisEnv

from . import service
from .dto import TickResponse


def _check_cron_secret(authorization: Optional[str]) -> None:
    if not RedisEnv.JOBS_CRON_SECRET:
        # disabled: look like any unknown path
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    expected = f"Bearer {RedisEnv.JOBS_CRON_SECRET}"
    if not authorization or not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid cron secret")


def tick(*, authorization: Optional[str]) -> TickResponse:
    _check_cron_secret(authorization)
    return TickResponse.model_validate(service.run_scheduled_jobs())
