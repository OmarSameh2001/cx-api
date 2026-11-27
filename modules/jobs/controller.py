import hmac
from typing import Optional


from common.errors import AppError
from config import RedisEnv

from . import service
from .dto import TickResponse


def _check_cron_secret(authorization: Optional[str]) -> None:
    if not RedisEnv.JOBS_CRON_SECRET:
        # disabled: look like any unknown path
        raise AppError(404, "common.not_found")
    expected = f"Bearer {RedisEnv.JOBS_CRON_SECRET}"
    if not authorization or not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise AppError(401, "jobs.invalid_cron_secret")


def tick(*, authorization: Optional[str]) -> TickResponse:
    _check_cron_secret(authorization)
    return TickResponse.model_validate(service.run_scheduled_jobs())
