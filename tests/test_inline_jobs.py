"""The no-worker path: inline runner, retries, and the cron tick endpoint."""

import pytest

from common.worker import inline
from common.worker.registry import Job
from config import RedisEnv
from modules.jobs import service as jobs_service

SECRET = "test-cron-secret"


@pytest.fixture(autouse=True)
def _no_redis_no_sleep(monkeypatch):
    monkeypatch.setattr(inline, "get_redis", lambda: None)
    monkeypatch.setattr(inline.time, "sleep", lambda s: None)
    monkeypatch.setattr(RedisEnv, "JOBS_RUNNER", "inline")
    monkeypatch.setattr(RedisEnv, "JOBS_CRON_SECRET", SECRET)


def _only_jobs(monkeypatch, *jobs):
    monkeypatch.setattr(inline, "JOBS", {j.name: j for j in jobs})


def test_inline_run_retries_then_succeeds():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("blip")
        return "done"

    run = inline.run(Job("t.flaky", flaky))
    assert run.ok and run.result == "done" and run.attempts == 3


def test_inline_run_logs_to_failed_jobs_after_last_retry(monkeypatch):
    logged = []
    monkeypatch.setattr(inline, "_record_failure", lambda job, run_id, kw, retries, exc: logged.append((job.name, retries)))

    def broken():
        raise ValueError("nope")

    run = inline.run(Job("t.broken", broken))
    assert not run.ok
    assert run.attempts == RedisEnv.JOB_MAX_RETRIES + 1
    assert logged == [("t.broken", RedisEnv.JOB_MAX_RETRIES)]


def test_tick_runs_only_scheduled_jobs(monkeypatch):
    ran = []
    _only_jobs(
        monkeypatch,
        Job("t.every_minute", lambda: ran.append("sched") or 1, 60),
        Job("t.on_demand", lambda: ran.append("demand")),
    )
    tick = inline.run_due_jobs()
    assert ran == ["sched"]
    assert [r.name for r in tick.ran] == ["t.every_minute"]


class _ClaimedRedis:
    def set(self, *a, **kw):
        return None  # key already there: ran recently


def test_tick_skips_jobs_that_ran_recently(monkeypatch):
    monkeypatch.setattr(inline, "get_redis", lambda: _ClaimedRedis())
    _only_jobs(monkeypatch, Job("t.every_minute", lambda: 1, 60))
    tick = inline.run_due_jobs()
    assert tick.ran == [] and tick.not_due == ["t.every_minute"]


def test_celery_mode_tick_does_nothing(monkeypatch):
    monkeypatch.setattr(RedisEnv, "JOBS_RUNNER", "celery")
    monkeypatch.setattr(inline, "run_due_jobs", lambda: pytest.fail("must not run inline"))
    assert jobs_service.run_scheduled_jobs() == {"runner": "celery"}


def test_tick_endpoint_needs_the_secret(client, monkeypatch):
    _only_jobs(monkeypatch, Job("t.every_minute", lambda: 7, 60))
    assert client.post("/internal/jobs/tick").status_code == 401
    assert client.post("/internal/jobs/tick", headers={"Authorization": "Bearer wrong"}).status_code == 401
    res = client.post("/internal/jobs/tick", headers={"Authorization": f"Bearer {SECRET}"})
    assert res.status_code == 200
    body = res.json()
    assert body["runner"] == "inline"
    assert body["ran"] == [{"name": "t.every_minute", "ok": True, "attempts": 1, "result": 7, "error": None}]


def test_tick_endpoint_is_hidden_without_a_secret(client, monkeypatch):
    monkeypatch.setattr(RedisEnv, "JOBS_CRON_SECRET", "")
    assert client.get("/internal/jobs/tick").status_code == 404
