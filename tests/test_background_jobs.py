"""Worker pieces that don't need Redis or Celery running: the Redis rate
limiter's fallback, the expiry sweep, and the retry/failed-job policy."""

from datetime import timedelta

import redis
from celery import Celery

from common import rate_limit
from common.rate_limit import RedisSlidingWindowLimiter, SlidingWindowLimiter
from common.worker import base_task
from common.worker.base_task import JobTask
from config import RedisEnv
from modules.jobs import service as jobs_service
from modules.submissions import repository as subs_repo
from modules.submissions import service as subs_service


class _FakeRedis:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def register_script(self, _lua):
        def run(keys, args):
            self.calls.append((keys, args))
            if self.error:
                raise self.error
            return self.result

        return run


def test_redis_limiter_allows_when_script_returns_nil(monkeypatch):
    fake = _FakeRedis(result=None)
    monkeypatch.setattr(rate_limit, "get_redis", lambda: fake)
    limiter = RedisSlidingWindowLimiter(SlidingWindowLimiter())
    assert limiter.hit("public-submit:t:a@b.io", 5, 60) is None
    (keys, args), = fake.calls
    # the key is hashed and prefixed: no email or IP is stored in Redis
    assert keys[0].startswith(RedisEnv.REDIS_KEY_PREFIX + "rl:")
    assert "a@b.io" not in keys[0]
    assert args[1:3] == [60, 5]


def test_redis_limiter_returns_retry_after_when_full(monkeypatch):
    monkeypatch.setattr(rate_limit, "get_redis", lambda: _FakeRedis(result=b"12.5"))
    limiter = RedisSlidingWindowLimiter(SlidingWindowLimiter())
    assert limiter.hit("k", 1, 60) == 12.5


def test_redis_limiter_falls_back_to_memory_when_redis_is_down(monkeypatch):
    fake = _FakeRedis(error=redis.ConnectionError("down"))
    monkeypatch.setattr(rate_limit, "get_redis", lambda: fake)
    limiter = RedisSlidingWindowLimiter(SlidingWindowLimiter())
    assert limiter.hit("k", 1, 60) is None
    assert limiter.hit("k", 1, 60) is not None  # counted in memory


def test_expiry_sweep_uses_the_grace_period(monkeypatch):
    seen = {}

    def fake_expire(db, cutoff):
        seen["cutoff"] = cutoff
        return 3

    monkeypatch.setattr(subs_repo, "expire_open_submissions_before", fake_expire)
    now = subs_service._now()
    monkeypatch.setattr(subs_service, "_now", lambda: now)
    assert subs_service.expire_abandoned_attempts(db=None) == 3
    assert seen["cutoff"] == now - subs_service.GRACE


def test_jobs_retry_with_backoff_from_env():
    assert JobTask.autoretry_for == (Exception,)
    assert JobTask.max_retries == RedisEnv.JOB_MAX_RETRIES
    assert JobTask.retry_backoff is True
    assert JobTask.retry_backoff_max == RedisEnv.JOB_RETRY_BACKOFF_MAX_SECONDS


def _demo_task():
    app = Celery("test", set_as_current=False)

    @app.task(base=JobTask, name="demo.task", shared=False)
    def demo():
        return None

    return demo


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_final_failure_is_logged_to_failed_jobs(monkeypatch):
    recorded = {}
    monkeypatch.setattr(base_task, "SessionLocal", _Session)
    monkeypatch.setattr(jobs_service, "record_failure", lambda db, **kw: recorded.update(kw))

    task = _demo_task()
    task.push_request(retries=3)
    try:
        task.on_failure(ValueError("boom"), "tid-1", (1,), {"a": 2}, None)
    finally:
        task.pop_request()

    assert recorded["task_id"] == "tid-1"
    assert recorded["task_name"] == "demo.task"
    assert recorded["retries"] == 3
    assert str(recorded["error"]) == "boom"


def test_failure_logging_errors_are_swallowed(monkeypatch):
    def broken(db, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(base_task, "SessionLocal", _Session)
    monkeypatch.setattr(jobs_service, "record_failure", broken)
    task = _demo_task()
    task.push_request(retries=0)
    try:
        task.on_failure(ValueError("boom"), "tid-2", (), {}, None)  # must not raise
    finally:
        task.pop_request()


def test_purge_keeps_the_retention_window(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        jobs_service.repository, "delete_failed_jobs_before",
        lambda db, cutoff: seen.setdefault("cutoff", cutoff) and 4,
    )
    assert jobs_service.purge_old_failures(db=None) == 4
    age = subs_service._now() - seen["cutoff"]
    assert abs(age - timedelta(days=RedisEnv.FAILED_JOB_RETENTION_DAYS)) < timedelta(seconds=5)
